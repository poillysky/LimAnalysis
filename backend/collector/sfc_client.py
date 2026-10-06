import logging
import re
import time
import urllib.parse
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class NetworkUnreachableError(Exception):
    pass


class AccountError(Exception):
    pass


class RetryableError(Exception):
    pass


class SessionExpiredError(Exception):
    pass


def try_login_account(config: dict, username: str, password: str) -> requests.Session:
    sfc_logon_url = f"{config['sfc_base_url'].rstrip('/')}{config['sfc_logon_path']}"
    encoded_url = urllib.parse.quote(sfc_logon_url, safe="")
    sso_url = f"{config['sso_login_url']}?url={encoded_url}"
    session = requests.Session()
    try:
        check = session.get(config["sso_login_url"], timeout=10)
        if check.status_code >= 500:
            raise NetworkUnreachableError(f"SSO 服务器错误 HTTP {check.status_code}")
    except requests.exceptions.Timeout as exc:
        raise NetworkUnreachableError("连接 SSO 超时") from exc
    except requests.exceptions.ConnectionError as exc:
        raise NetworkUnreachableError("无法连接 SSO") from exc

    response = session.post(
        sso_url,
        data={
            "txtUserNo": username,
            "txtPass": password,
            "txtUrl": sfc_logon_url,
            "txtEffectiveTime": "720",
        },
        timeout=30,
        allow_redirects=False,
    )
    if response.status_code in (401, 403):
        raise AccountError("账号密码错误或无权限")
    if response.status_code in (429, 503):
        raise RetryableError("服务器限流或暂时不可用")
    if response.status_code != 200:
        raise RetryableError(f"登录请求失败 HTTP {response.status_code}")
    text = response.text.strip()
    if text != "1":
        raise AccountError(text.replace("未知的", "").strip() or "登录失败")

    sso_base = config["sso_login_url"].rsplit("/", 1)[0]
    validate_url = f"{sso_base}/ValidateTaken.aspx?url={urllib.parse.quote(sfc_logon_url)}"
    validate = session.get(validate_url, timeout=10, allow_redirects=True)
    if validate.status_code != 200:
        raise AccountError(f"ValidateTaken 失败 HTTP {validate.status_code}")

    verify_url = f"{config['sfc_base_url'].rstrip('/')}{config['sfc_logon_path']}"
    verify = session.get(verify_url, timeout=10)
    if verify.status_code != 200:
        raise AccountError(f"无法访问 SFC HTTP {verify.status_code}")
    if "login" in verify.url.lower() or "sso" in verify.url.lower():
        raise AccountError("Session 无效，被重定向到登录页")
    if len(verify.text) < 100:
        raise AccountError("SFC 响应异常")
    try:
        session.get(
            f"{config['sfc_base_url'].rstrip('/')}/SFCS/Views/Default.aspx",
            timeout=10,
            allow_redirects=True,
        )
    except Exception as exc:
        logger.warning("访问 SFC 默认页失败: %s", exc)
    return session


def login_with_pool(config: dict, accounts: list[dict], retry: int = 3):
    logs = []

    def add(level: str, message: str):
        logs.append(
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": level,
                "message": message,
            }
        )

    if not accounts:
        add("error", "没有可用账号")
        return None, None, logs
    for account in accounts:
        for attempt in range(retry):
            try:
                add("info", f"尝试账号 {account['username']}（第 {attempt + 1} 次）")
                session = try_login_account(config, account["username"], account["password"])
                add("success", f"账号 {account['username']} 登录成功")
                return session, account, logs
            except NetworkUnreachableError as exc:
                add("error", str(exc))
                return None, account, logs
            except AccountError as exc:
                add("warning", f"{account['username']}: {exc}")
                break
            except RetryableError as exc:
                add("warning", str(exc))
                if attempt < retry - 1:
                    time.sleep(5)
                    continue
                break
            except requests.exceptions.Timeout:
                add("warning", "请求超时")
                if attempt < retry - 1:
                    time.sleep(5)
                    continue
                break
            except requests.exceptions.ConnectionError:
                add("error", "无法连接服务器")
                return None, account, logs
    add("error", "所有账号都失败")
    return None, None, logs


def download_project_csv(
    session: requests.Session, config: dict, project: dict, retry: int = 3
) -> bytes:
    url = (
        f"{config['sfc_base_url'].rstrip('/')}{config['sfc_data_path']}"
        f"?p={project['sfc_code']}&&type={project['btype']}"
    )
    last_error = None
    for attempt in range(retry):
        try:
            page = session.get(url, timeout=30)
            if "login" in page.url.lower() or page.status_code == 401:
                raise SessionExpiredError("Session 已过期")
            if page.status_code != 200:
                raise RetryableError(f"访问数据页失败 HTTP {page.status_code}")
            form_data = {
                "ctl00$pageBody$txtLine": config.get("line_option") or "all",
                "ctl00$pageBody$txtSection": config.get("section_option") or "LIM",
                "ctl00$pageBody$btnDownload": "下载",
            }
            for name, pattern in (
                ("__VIEWSTATE", r'name="__VIEWSTATE"[^>]*value="([^"]*)"'),
                ("__VIEWSTATEGENERATOR", r'name="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"'),
                ("__EVENTVALIDATION", r'name="__EVENTVALIDATION"[^>]*value="([^"]*)"'),
                (
                    "ctl00$pageBody$txtStartTime",
                    r'name="ctl00\$pageBody\$txtStartTime"[^>]*value="([^"]*)"',
                ),
                (
                    "ctl00$pageBody$txtEndTime",
                    r'name="ctl00\$pageBody\$txtEndTime"[^>]*value="([^"]*)"',
                ),
            ):
                match = re.search(pattern, page.text)
                if match:
                    form_data[name] = match.group(1)
            response = session.post(url, data=form_data, headers={"Referer": url}, timeout=120)
            if "login" in response.url.lower() or response.status_code == 401:
                raise SessionExpiredError("Session 已过期")
            if response.status_code != 200:
                raise RetryableError(f"下载失败 HTTP {response.status_code}")
            head = response.content[:80].lstrip().lower()
            if head.startswith(b"<!doctype") or head.startswith(b"<html"):
                raise SessionExpiredError("返回了 HTML，可能 Session 已过期")
            return response.content
        except SessionExpiredError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < retry - 1:
                time.sleep(5)
    raise RetryableError(f"下载失败，已重试 {retry} 次: {last_error}")
