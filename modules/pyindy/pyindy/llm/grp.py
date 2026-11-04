import json

import requests
from urllib.error import HTTPError

class GRPNCM:
    def __init__(self, url="http://example.local:8001/ncms"):
        self.url = url

    def get_response(self, speaker, query, history=[]):
        try:
            response = ""

            json_data = {
                "id": speaker,
                "input": query,
                "contexts": history,
            }
            response = requests.post(
                self.url, data=json.dumps(json_data)
            )
            res_data = response.json()
            response = res_data["output"]
        except HTTPError as http_err:
            print(f"HTTPエラーが発生しました: {http_err}")
            return None
        except ConnectionError as conn_err:
            print(f"接続エラーが発生しました: {conn_err}")
            return None
        except Timeout as timeout_err:
            print(f"タイムアウトが発生しました: {timeout_err}")
            return None
        except RequestException as req_err:
            print(f"予期しないエラーが発生しました: {req_err}")
            return None

        return response
