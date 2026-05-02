#!/usr/bin/env bash
# test-pipeline.sh — drive /crawl + /analyze + /ask directly with curl.
# No agent, no Photon. Just the Python server and GMI.
#
# Usage:
#   ./scripts/test-pipeline.sh <URL>                            # crawl + analyze
#   ./scripts/test-pipeline.sh <URL> "question 1" "question 2"  # then ask each
#   ./scripts/test-pipeline.sh "question only"                  # uses cached prior /analyze response
#
# State (leaks + summary from the last analyze) is cached at /tmp/lease_state.json
# so follow-up questions in a separate invocation still have context.

set -euo pipefail

SERVER="${SERVER_BASE_URL:-http://127.0.0.1:8000}"
STATE_FILE="/tmp/lease_state.json"
JQ="$(command -v jq || true)"

if [[ -z "$JQ" ]]; then
  echo "error: jq is required (brew install jq)" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  cat <<EOF
Usage:
  $0 <URL>                              crawl + analyze, save to $STATE_FILE
  $0 <URL> "question 1" "question 2"    crawl + analyze, then ask each question
  $0 "question only"                    ask using last cached /analyze response
  $0 --auto <URL>                       crawl + analyze + auto-explore (Claude
                                        generates and answers up to 10 follow-ups)
  $0 --auto                             auto-explore using cached /analyze

Env:
  SERVER_BASE_URL  default http://127.0.0.1:8000
  MAX_FOLLOWUPS    default 10 (only used with --auto)
EOF
  exit 0
fi

is_url() { [[ "$1" =~ ^https?:// ]]; }

call_crawl() {
  local url="$1"
  echo "==> POST /crawl url=$url" >&2
  local resp
  resp=$(curl -sS -m 120 -X POST "$SERVER/crawl" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg u "$url" '{url: $u}')")
  local err
  err=$(echo "$resp" | jq -r '.detail // empty' 2>/dev/null || true)
  if [[ -n "$err" && "$err" != "null" ]]; then
    echo "    /crawl error: $err" >&2
    return 1
  fi
  local bytes
  bytes=$(echo "$resp" | jq -r '.content | length')
  local backend
  backend=$(echo "$resp" | jq -r '.metadata.backend // "?"' 2>/dev/null || echo "?")
  echo "    /crawl ok bytes=$bytes backend=$backend" >&2
  echo "$resp"
}

call_analyze() {
  local crawl_resp="$1"
  local source_url="$2"
  echo "==> POST /analyze source=$source_url" >&2
  local body
  body=$(echo "$crawl_resp" | jq --arg src "$source_url" '{content: .content, context: [], source_url: $src}')
  local resp
  resp=$(curl -sS -m 180 -X POST "$SERVER/analyze" \
    -H "Content-Type: application/json" \
    -d "$body")
  local n_leaks
  n_leaks=$(echo "$resp" | jq '.leaks | length')
  echo "    /analyze ok leaks=$n_leaks" >&2
  echo "$resp"
}

call_ask() {
  local question="$1"
  local state_file="$2"
  echo "==> POST /ask q=\"$question\"" >&2
  local body
  body=$(jq --arg q "$question" '{question: $q, leaks: .leaks, summary: .summary, history: []}' "$state_file")
  local resp
  resp=$(curl -sS -m 180 -X POST "$SERVER/ask" \
    -H "Content-Type: application/json" \
    -d "$body")
  local answer
  answer=$(printf '%s' "$resp" | jq -r '.answer // .detail // "ERROR: " + (. | tostring)')
  echo "    /ask answer:" >&2
  printf '%s\n' "$answer"
}

print_summary() {
  local analyze_resp="$1"
  echo
  echo "--- SUMMARY ---"
  echo "$analyze_resp" | jq -r '.summary'
  echo
  echo "--- LEAKS ($(echo "$analyze_resp" | jq '.leaks | length')) ---"
  echo "$analyze_resp" | jq -r '.leaks[] | "  [\(.severity)] \(.title): \(.detail)"'
  echo
}

# Auto-explore: ask Claude to generate follow-up questions about the listing,
# then call /ask for each. Up to MAX_FOLLOWUPS (default 10) total rounds.
# Each round, Claude sees prior Q&A and decides what to ask next, OR stops by
# answering with the literal token "DONE".
auto_explore() {
  local state_file="$1"
  local max="${MAX_FOLLOWUPS:-10}"
  local question_history="[]"

  echo
  echo "==> AUTO-EXPLORE (max $max rounds)" >&2

  for ((round=1; round<=max; round++)); do
    # Ask Claude to propose the next question. Use /ask with a meta-prompt.
    local meta_q
    meta_q=$(printf '%s' "Based on the listing data and the prior Q&A history, what is the single most useful next question to ask? Reply with ONLY the question (no preamble). If nothing else is worth asking, reply with the literal word DONE." )

    local body
    body=$(jq --arg q "$meta_q" --argjson hist "$question_history" \
      '{question: $q, leaks: .leaks, summary: .summary, history: $hist}' "$state_file")
    local proposed
    proposed=$(curl -sS -m 180 -X POST "$SERVER/ask" \
      -H "Content-Type: application/json" -d "$body" \
      | jq -r '.answer // ""')

    proposed=$(printf '%s' "$proposed" | sed 's/^["[:space:]]*//; s/["[:space:]]*$//')

    if [[ -z "$proposed" || "$proposed" == "DONE" || "$proposed" == DONE* ]]; then
      echo "    [$round/$max] Claude says DONE — stopping." >&2
      break
    fi

    echo
    echo "--- Round $round/$max ---"
    echo "Q: $proposed"

    # Now answer the proposed question.
    local ans_body
    ans_body=$(jq --arg q "$proposed" --argjson hist "$question_history" \
      '{question: $q, leaks: .leaks, summary: .summary, history: $hist}' "$state_file")
    local answer
    answer=$(curl -sS -m 180 -X POST "$SERVER/ask" \
      -H "Content-Type: application/json" -d "$ans_body" \
      | jq -r '.answer // "(no answer)"')

    echo "A: $answer"

    # Append to history so the next round has context.
    question_history=$(jq -n --argjson hist "$question_history" --arg q "$proposed" --arg a "$answer" \
      '$hist + [{role:"user",content:$q},{role:"assistant",content:$a}]')
  done

  echo
  echo "==> AUTO-EXPLORE done after $((round - 1)) round(s)." >&2
}

main() {
  local mode="manual"
  if [[ "${1:-}" == "--auto" ]]; then
    mode="auto"
    shift
  fi

  local first="${1:-}"
  [[ -n "$first" ]] && shift || true
  local questions=("$@")

  if [[ -n "$first" ]] && is_url "$first"; then
    local crawl_resp
    crawl_resp=$(call_crawl "$first")
    local analyze_resp
    analyze_resp=$(call_analyze "$crawl_resp" "$first")
    printf '%s\n' "$analyze_resp" > "$STATE_FILE"
    print_summary "$analyze_resp"
  elif [[ -n "$first" ]]; then
    # Single arg, not a URL — treat it as a question against cached state.
    questions=("$first" "${questions[@]}")
  fi

  # Auto mode needs cached state.
  if [[ "$mode" == "auto" ]]; then
    if [[ ! -f "$STATE_FILE" ]]; then
      echo "error: no cached state at $STATE_FILE; run --auto with a URL or after a manual run" >&2
      exit 1
    fi
    auto_explore "$STATE_FILE"
    return
  fi

  if [[ ${#questions[@]} -gt 0 ]]; then
    if [[ ! -f "$STATE_FILE" ]]; then
      echo "error: no cached state at $STATE_FILE; run with a URL first" >&2
      exit 1
    fi
    for q in "${questions[@]}"; do
      echo
      call_ask "$q" "$STATE_FILE"
    done
  fi
}

main "$@"
