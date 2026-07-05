"""
텔레그램으로 거래 이벤트를 알려주는 최소 구현체. python-telegram-bot 같은 별도
패키지 없이 표준 라이브러리 urllib만으로 Bot API를 호출한다(의존성 추가 없음).
알림 실패가 거래 로직에 영향을 주면 안 되므로 예외는 여기서 삼키고 콘솔에만 출력한다.
"""
import json
import urllib.request
import urllib.error


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled and bool(bot_token) and bool(chat_id)

    def send(self, message: str):
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = json.dumps({"chat_id": self.chat_id, "text": message}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"[TELEGRAM_ERROR] {e}")
