"""
数据存取层：自动在「本地文件」和「GitHub 仓库」之间切换。
- 如果配置了 GITHUB_TOKEN + GITHUB_REPO → 走 GitHub
- 否则 → 走本地 diary.json / images/
"""
import base64
import io
import json
import os
import uuid
import requests

try:
    import streamlit as st
    def _secret(key, default=None):
        try:
            return st.secrets.get(key, default)
        except Exception:
            return default
except ImportError:
    def _secret(key, default=None):
        return os.environ.get(key, default)

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# ==================== 配置 ====================
GITHUB_API = "https://api.github.com"
MAX_IMAGE_SIZE = 1600
IMAGE_QUALITY = 85

DIARY_FILE = "diary.json"
IMAGE_DIR = "images"
os.makedirs(IMAGE_DIR, exist_ok=True)


def is_remote():
    return bool(_secret("GITHUB_TOKEN")) and bool(_secret("GITHUB_REPO"))


# ==================== 本地实现 ====================
def _local_load():
    if os.path.exists(DIARY_FILE):
        with open(DIARY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _local_save(entries):
    with open(DIARY_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _local_load_image(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _local_save_image(data, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _local_delete_image(path):
    if path and os.path.exists(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return False


# ==================== GitHub 实现 ====================
def _gh_headers():
    return {
        "Authorization": f"Bearer {_secret('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_repo():
    return _secret("GITHUB_REPO")


def _gh_branch():
    return _secret("GITHUB_BRANCH", "main")


def _gh_get_file(path):
    """返回 (content_bytes, sha)，不存在则 (None, None)"""
    url = f"{GITHUB_API}/repos/{_gh_repo()}/contents/{path}"
    r = requests.get(url, headers=_gh_headers(),
                     params={"ref": _gh_branch()}, timeout=20)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    data = r.json()
    return base64.b64decode(data["content"]), data["sha"]


def _gh_put_file(path, content_bytes, sha=None, message="update"):
    url = f"{GITHUB_API}/repos/{_gh_repo()}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": _gh_branch(),
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=_gh_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def _gh_delete_file(path, sha, message="delete"):
    url = f"{GITHUB_API}/repos/{_gh_repo()}/contents/{path}"
    payload = {"message": message, "sha": sha, "branch": _gh_branch()}
    r = requests.delete(url, headers=_gh_headers(), json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


# ==================== 对外接口 ====================
def load_entries():
    if is_remote():
        content, _ = _gh_get_file("diary.json")
        if content is None:
            return []
        return json.loads(content.decode("utf-8"))
    return _local_load()


def save_entries(entries):
    if is_remote():
        content = json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")
        _, sha = _gh_get_file("diary.json")
        _gh_put_file("diary.json", content, sha=sha,
                     message=f"update diary ({len(entries)} entries)")
    else:
        _local_save(entries)


def load_image_bytes(path):
    """读取图片二进制；不存在返回 None"""
    if not path:
        return None
    if is_remote():
        try:
            content, _ = _gh_get_file(path)
            return content
        except Exception:
            return None
    return _local_load_image(path)


def delete_image(path):
    if not path:
        return False
    if is_remote():
        try:
            _, sha = _gh_get_file(path)
            if sha:
                _gh_delete_file(path, sha, message=f"delete {path}")
                return True
        except Exception:
            return False
    else:
        return _local_delete_image(path)
    return False


def _process_image(file, ext):
    """压缩图片，返回 bytes"""
    try:
        if _HAS_PIL:
            file.seek(0)
            img = Image.open(file)
            if ext == "jpg" and img.mode in ("RGBA", "P", "LA"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = bg
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            if max(img.size) > MAX_IMAGE_SIZE:
                ratio = MAX_IMAGE_SIZE / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            fmt = "JPEG" if ext == "jpg" else ext.upper()
            img.save(buf, format=fmt, quality=IMAGE_QUALITY, optimize=True)
            return buf.getvalue()
    except Exception:
        pass
    file.seek(0)
    return file.read()


def save_image(uploaded_files, entry_id):
    """压缩 + 保存图片，返回文件路径列表（路径是 images/xxx 形式的相对路径）"""
    saved_paths = []
    for file in uploaded_files:
        ext = file.name.split(".")[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
        if ext in ("jpeg", "webp"):
            ext = "jpg"
        path = f"images/entry_{entry_id}_{uuid.uuid4().hex[:8]}.{ext}"
        data = _process_image(file, ext)
        if is_remote():
            _gh_put_file(path, data, sha=None,
                         message=f"upload image for entry {entry_id}")
        else:
            _local_save_image(data, path)
        saved_paths.append(path)
    return saved_paths


# ==================== 备份 / 恢复 ====================
def create_backup_zip(entries):
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diary.json",
                    json.dumps(entries, ensure_ascii=False, indent=2))
        for e in entries:
            for img in e.get("images", []):
                data = load_image_bytes(img)
                if data:
                    zf.writestr(img, data)
    buf.seek(0)
    return buf.getvalue()


def import_backup_zip(uploaded_file):
    import zipfile
    with zipfile.ZipFile(uploaded_file) as zf:
        if "diary.json" not in zf.namelist():
            raise ValueError("压缩包里找不到 diary.json")
        imported = json.loads(zf.read("diary.json").decode("utf-8"))

        # 先备份当前 diary.json（本地模式下）
        if not is_remote() and os.path.exists(DIARY_FILE):
            ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                import shutil
                shutil.copy(DIARY_FILE, f"diary_backup_{ts}.json")
            except Exception:
                pass

        # 上传所有图片
        for name in zf.namelist():
            if name == "diary.json" or name.endswith("/"):
                continue
            data = zf.read(name)
            if is_remote():
                _, sha = _gh_get_file(name)
                _gh_put_file(name, data, sha=sha, message=f"import {name}")
            else:
                _local_save_image(data, name)

        save_entries(imported)
        return len(imported)


# ==================== 诊断 ====================
def check_connection():
    """返回 (ok, message)，用于设置页显示"""
    if not is_remote():
        return True, "📁 本地文件模式（diary.json + images/）"
    try:
        url = f"{GITHUB_API}/repos/{_gh_repo()}"
        r = requests.get(url, headers=_gh_headers(), timeout=10)
        if r.status_code == 200:
            data = r.json()
            vis = "🔒 私有" if data.get("private") else "⚠️ 公开"
            return True, f"✅ 已连接 {data['full_name']}（{vis}）"
        return False, f"❌ HTTP {r.status_code}：{r.text[:200]}"
    except Exception as e:
        return False, f"❌ 连接失败：{e}"