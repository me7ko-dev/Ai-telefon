#!/usr/bin/env bash
# Примерни заявки към 4-те инструмента – както ще ги вика ElevenLabs агентът.
# Употреба:  ./scripts/sample_requests.sh  [адрес]   (по подразбиране http://localhost:8000)
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${1:-http://localhost:8000}"
SLUG="${SLUG:-demo}"
SECRET="${TOOL_SECRET:-$(grep -E '^TOOL_SECRET=' .env | cut -d= -f2-)}"
URL="$BASE/api/b/$SLUG/tools"
DAY="${DAY:-$(python3 -c 'import datetime as d; t=d.date.today()+d.timedelta(1); t+=d.timedelta((7-t.weekday())%7 if t.weekday()>4 else 0); print(t)')}"

call() {
  echo; echo "▶ $1  $2"
  curl -sS -X POST "$URL/$1" -H "Content-Type: application/json" -H "X-Tool-Secret: $SECRET" -d "$2" \
    | python3 -m json.tool --no-ensure-ascii
}

echo "Дата за теста: $DAY (следващия делничен ден)"
call check_availability "{\"service\": \"мъжко подстригване\", \"date\": \"$DAY\"}"
call book_appointment   "{\"name\": \"Иван Петров\", \"phone\": \"0888 123 456\", \"service\": \"мъжко подстригване\", \"date\": \"$DAY\", \"time\": \"10:00\"}"
call book_appointment   "{\"name\": \"Георги\", \"phone\": \"0899 111 222\", \"service\": \"мъжко подстригване\", \"date\": \"$DAY\", \"time\": \"10:00\"}"
call check_availability "{\"service\": \"мъжко подстригване\", \"date\": \"$DAY\"}"
call cancel_appointment "{\"phone\": \"+359888123456\", \"date\": \"$DAY\"}"
call take_message       "{\"name\": \"Мария\", \"phone\": \"0877 000 111\", \"message\": \"Искам оферта за булчинска прическа.\"}"
call check_availability "{\"service\": \"маникюр\", \"date\": \"$DAY\"}"

echo; echo "▶ без ключ (очаква се 401)"
curl -sS -o /dev/null -w "HTTP %{http_code}\n" -X POST "$URL/take_message" -H "Content-Type: application/json" -d '{}'
