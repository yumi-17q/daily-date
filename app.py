import streamlit as st
import streamlit.components.v1 as components
import re
import calendar as cal_mod
from datetime import datetime, timedelta, date
from collections import Counter

import storage
from storage import is_remote, check_connection

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# ==================== 配置 ====================
MOOD_EMOJIS = ["😫", "😞", "😐", "🙂", "😄"]
MOOD_NAMES  = ["很差", "不好", "一般", "不错", "很好"]
TRASH_RETENTION_DAYS = 30

STOPWORDS = set(
    "的了是在我有和就不人都一个上也很到说要去你会着没有看好自己这那"
    "为所以但是因为如果虽然可是而且然后还再又啊吧呢吗哦嗯只把被给让对"
    "与及其此些什么怎样如何可以可能应该还是就是真是"
)

NAV_OPTIONS = ["✍️ 写日记", "📖 查看日记", "📅 日历视图",
               "🧠 总结日记", "🗑️ 回收站", "⚙️ 设置"]

# ==================== 页面配置 ====================
st.set_page_config(page_title="我的日记本", page_icon="📔", layout="centered")


# ==================== 密码保护 ====================
def _secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def password_gate():
    if st.session_state.get("_authed"):
        return True
    expected = _secret("APP_PASSWORD")
    if not expected:
        return True

    st.title("📔 我的日记本")
    st.caption("🔒 请输入访问密码")
    pw = st.text_input("密码", type="password", key="_pw",
                       label_visibility="collapsed",
                       placeholder="密码")
    if st.button("登录", type="primary", use_container_width=True):
        if pw == expected:
            st.session_state._authed = True
            st.rerun()
        else:
            st.error("❌ 密码错误")
    return False


if not password_gate():
    st.stop()

st.title("📔 我的日记本")


# ==================== 带缓存的存取 ====================
@st.cache_data(ttl=60, show_spinner=False)
def get_entries():
    return storage.load_entries()


@st.cache_data(ttl=600, show_spinner=False)
def get_image(path):
    return storage.load_image_bytes(path)


def refresh_all():
    st.cache_data.clear()


def save_all(entries):
    storage.save_entries(entries)
    refresh_all()


# ==================== 摘要工具 ====================
def _tokenize(text):
    if _HAS_JIEBA:
        return [w for w in jieba.cut(text)
                if len(w) > 1 and w not in STOPWORDS and not w.isdigit()]
    tokens = []
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    tokens += [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    tokens += re.findall(r"[a-zA-Z]{2,}", text.lower())
    return tokens


def _split_sentences(text):
    text = re.sub(r"\s+", " ", text)
    raw = re.split(r"[。！？!?\n；;]", text)
    return [s.strip() for s in raw if len(s.strip()) >= 4]


def summarize_texts(texts, top_n=6):
    full = "\n".join(texts)
    sents = _split_sentences(full)
    if len(sents) <= top_n:
        return sents
    freq = Counter(_tokenize(full))
    if not freq:
        return sents[:top_n]
    max_f = max(freq.values())
    scored = []
    for s in sents:
        ws = _tokenize(s)
        if not ws:
            continue
        score = sum(freq.get(w, 0) / max_f for w in ws) / (len(ws) ** 0.6)
        scored.append((score, s))
    top = sorted(scored, key=lambda x: -x[0])[:top_n]
    order = {s: i for i, s in enumerate(sents)}
    top.sort(key=lambda x: order[x[1]])
    return [s for _, s in top]


def top_keywords(texts, k=12):
    return [w for w, _ in Counter(_tokenize("\n".join(texts))).most_common(k)]


# ==================== 统计 ====================
def calc_streak(entries):
    dates = set()
    for e in entries:
        if e.get("deleted"):
            continue
        try:
            dates.add(datetime.strptime(e["date"][:10], "%Y-%m-%d").date())
        except Exception:
            pass
    if not dates:
        return 0
    today = date.today()
    if today in dates:
        start = today
    elif (today - timedelta(days=1)) in dates:
        start = today - timedelta(days=1)
    else:
        return 0
    n = 0
    d = start
    while d in dates:
        n += 1
        d -= timedelta(days=1)
    return n


def collect_tags(entries):
    tags = set()
    for e in entries:
        if e.get("deleted"):
            continue
        for t in e.get("tags", []):
            if t.strip():
                tags.add(t.strip())
    return sorted(tags)


def purge_expired_trash(entries):
    now = datetime.now()
    kept = []
    purged = 0
    for e in entries:
        if e.get("deleted"):
            da = e.get("deleted_at")
            if da:
                try:
                    dt = datetime.strptime(da, "%Y-%m-%d %H:%M")
                    if (now - dt).days >= TRASH_RETENTION_DAYS:
                        for p in e.get("images", []):
                            storage.delete_image(p)
                        purged += 1
                        continue
                except Exception:
                    pass
        kept.append(e)
    return kept, purged


# ==================== session_state ====================
defaults = {
    "diary_title": "", "diary_content": "", "diary_tags": "",
    "selected_mood": 3, "uploader_key": 0,
    "editing_id": None, "keep_images": [],
    "cal_year": date.today().year, "cal_month": date.today().month,
    "cal_selected": None, "pending_delete_id": None,
    "diary_date": date.today(),
    "diary_time": datetime.now().time().replace(second=0, microsecond=0),
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ==================== CSS ====================
st.markdown("""
<style>
:root {
    --c-accent: #4a9eff;
    --c-accent-rgb: 74, 158, 255;
    --c-soft-bg: rgba(128, 128, 128, 0.10);
    --c-border-soft: rgba(128, 128, 128, 0.30);
    --c-muted: rgba(128, 128, 128, 0.85);
}

/* 快捷键提示（桌面显示，手机隐藏） */
.kbd-hint {
    font-size: 0.85rem;
    color: var(--c-muted);
    margin-bottom: 6px;
}

/* 心情圆圈 */
[class*="st-key-mood_picker"] .stButton > button {
    border-radius: 50% !important;
    width: 56px !important; height: 56px !important;
    min-width: 56px !important; padding: 0 !important;
    font-size: 26px !important; line-height: 1 !important;
    border: 2px solid var(--c-border-soft) !important;
    background: transparent !important;
    transition: all 0.18s ease;
    box-shadow: none !important;
    margin: 0 auto !important;
    display: flex !important; align-items: center !important;
    justify-content: center !important;
}
[class*="st-key-mood_picker"] .stButton > button:hover {
    border-color: var(--c-accent) !important;
    transform: scale(1.06);
}
[class*="st-key-mood_picker"] .stButton > button[kind="primary"] {
    border-color: var(--c-accent) !important;
    background: rgba(var(--c-accent-rgb), 0.18) !important;
    box-shadow: 0 0 0 3px rgba(var(--c-accent-rgb), 0.25) !important;
}

/* 标签徽章 */
.tag-badge {
    display: inline-block;
    padding: 2px 9px;
    margin: 2px 4px 2px 0;
    background: rgba(var(--c-accent-rgb), 0.16);
    color: var(--c-accent);
    border-radius: 10px;
    font-size: 12px;
}

/* 统计卡片 */
.stat-card {
    background: linear-gradient(135deg,
        rgba(var(--c-accent-rgb), 0.06) 0%,
        rgba(var(--c-accent-rgb), 0.16) 100%);
    border-radius: 10px;
    padding: 12px 8px;
    text-align: center;
    border: 1px solid rgba(var(--c-accent-rgb), 0.22);
}
.stat-card .num {
    font-size: 22px;
    font-weight: 700;
    color: var(--c-accent);
    line-height: 1.2;
}
.stat-card .label {
    font-size: 11px;
    color: var(--c-muted);
    margin-top: 2px;
}

/* 日历热力图 */
div[data-testid="stHorizontalBlock"] {
    gap: 6px !important;
}
div[data-testid="stColumn"] {
    padding: 0 !important;
}
div[data-testid="stColumn"] div[data-testid="stMarkdownContainer"],
div[data-testid="stColumn"] div[data-testid="stMarkdownContainer"] > p {
    margin: 0 !important;
    padding: 0 !important;
}
[class*="st-key-calL"],
[class*="st-key-calE"] {
    margin: 0 !important;
    padding: 0 !important;
}
[class*="st-key-calL"] button,
[class*="st-key-calE"] button {
    width: 100% !important;
    height: 40px !important;
    min-height: 40px !important;
    max-height: 40px !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    border-radius: 8px !important;
    color: transparent !important;
    font-size: 0 !important;
    line-height: 0 !important;
    box-shadow: none !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
[class*="st-key-calL"] button:hover,
[class*="st-key-calE"] button:hover {
    transform: scale(1.08);
    box-shadow: 0 0 0 2px rgba(var(--c-accent-rgb), 0.45) !important;
}
[class*="st-key-calL1_"] button { background: rgba(var(--c-accent-rgb), 0.30) !important; }
[class*="st-key-calL2_"] button { background: rgba(var(--c-accent-rgb), 0.60) !important; }
[class*="st-key-calL3_"] button { background: rgba(var(--c-accent-rgb), 0.95) !important; }
[class*="st-key-calE"] button {
    background: var(--c-soft-bg) !important;
}
[class*="st-key-calEtoday"] button {
    background: var(--c-soft-bg) !important;
    box-shadow: inset 0 0 0 2px var(--c-border-soft) !important;
}
[class*="st-key-calEtoday"] button:hover {
    box-shadow: inset 0 0 0 2px var(--c-border-soft),
                0 0 0 2px rgba(var(--c-accent-rgb), 0.45) !important;
}

/* ===== 移动端适配（窄屏 < 768px）===== */
@media (max-width: 768px) {
    /* 关键：禁止所有横向列换行 → 防止 Streamlit 自动堆叠 */
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
    }
    /* 允许列收缩，均分宽度 */
    div[data-testid="stColumn"],
    div[data-testid="column"] {
        min-width: 0 !important;
        width: auto !important;
        flex-shrink: 1 !important;
        flex-grow: 1 !important;
        flex-basis: 0 !important;
        padding: 0 !important;
    }

    .block-container,
    [data-testid="stAppViewContainer"] > .main > .block-container {
        padding: 0.6rem 0.6rem 2rem 0.6rem !important;
        max-width: 100% !important;
    }

    h1 {
        font-size: 1.45rem !important;
        margin-bottom: 0.4rem !important;
    }
    h2 { font-size: 1.15rem !important; }
    h3 { font-size: 1rem !important; }

    /* 统计卡片 */
    .stat-card {
        padding: 8px 3px !important;
        border-radius: 8px !important;
    }
    .stat-card .num { font-size: 16px !important; }
    .stat-card .label {
        font-size: 9px !important;
        margin-top: 1px !important;
    }

    /* 心情圆圈缩小 */
    [class*="st-key-mood_picker"] .stButton > button {
        width: 40px !important;
        height: 40px !important;
        min-width: 40px !important;
        font-size: 20px !important;
        border-width: 1.5px !important;
    }

    /* 日历格子更矮 */
    [class*="st-key-calL"] button,
    [class*="st-key-calE"] button {
        height: 34px !important;
        min-height: 34px !important;
        max-height: 34px !important;
        border-radius: 6px !important;
    }

    /* 列间距 */
    div[data-testid="stHorizontalBlock"] {
        gap: 4px !important;
    }

    /* 按钮字号 */
    .stButton > button {
        padding: 0.45rem 0.6rem !important;
        font-size: 0.88rem !important;
    }

    /* expander 标题 */
    [data-testid="stExpander"] summary {
        font-size: 0.88rem !important;
    }

    /* iOS 输入框 16px 防缩放 */
    input, textarea, select,
    .stTextInput input, .stTextArea textarea {
        font-size: 16px !important;
    }

    .tag-badge {
        font-size: 11px !important;
        padding: 1px 7px !important;
    }

    hr { margin: 0.5rem 0 !important; }

    [data-testid="stFileUploader"] {
        font-size: 0.88rem !important;
    }

    .kbd-hint { display: none !important; }
}
</style>
""", unsafe_allow_html=True)


# ==================== 顶部工具条 ====================
col_a, col_b = st.columns([5, 1])
with col_b:
    if st.button("🔄 刷新", use_container_width=True, help="从云端重新拉取数据"):
        refresh_all()
        st.rerun()

# ==================== 侧边栏导航 ====================
if "pending_nav" in st.session_state and st.session_state.pending_nav:
    st.session_state.nav = st.session_state.pop("pending_nav")

page = st.sidebar.radio("导航", NAV_OPTIONS, key="nav")

entries = get_entries()

entries, _purged = purge_expired_trash(entries)
if _purged:
    save_all(entries)

active_entries  = [e for e in entries if not e.get("deleted")]
deleted_entries = [e for e in entries if e.get("deleted")]
streak = calc_streak(entries)


# ==================================================
# 页面一：写日记
# ==================================================
if page == "✍️ 写日记":
    editing_id = st.session_state.editing_id

    if st.session_state.pop("clear_diary", False):
        for k, v in [("diary_title", ""), ("diary_content", ""),
                     ("diary_tags", ""), ("selected_mood", 3),
                     ("diary_date", date.today()),
                     ("diary_time", datetime.now().time().replace(second=0, microsecond=0))]:
            st.session_state[k] = v
        st.session_state.editing_id = None
        st.session_state.keep_images = []
        st.session_state.uploader_key += 1

    if st.session_state.pop("diary_saved", False):
        st.balloons()

    if editing_id:
        st.subheader("✏️ 编辑日记")
        if st.button("← 退出编辑（不保存）"):
            st.session_state.editing_id = None
            st.session_state.keep_images = []
            st.session_state.diary_title = ""
            st.session_state.diary_content = ""
            st.session_state.diary_tags = ""
            st.session_state.selected_mood = 3
            st.session_state.diary_date = date.today()
            st.session_state.diary_time = datetime.now().time().replace(second=0, microsecond=0)
            st.session_state.uploader_key += 1
            st.rerun()
    else:
        st.subheader("今天发生了什么？")
        if not entries:
            st.info(
                "👋 欢迎使用！在这里写下你的第一篇日记吧。\n\n"
                "写好后点下方的 **💾 保存日记** 就会存起来。\n\n"
                "💡 小提示：上面可以改日期，想补写以前的日记也完全没问题。"
            )

    title = st.text_input("标题（可选）", placeholder="给今天起个标题...",
                          key="diary_title")

    st.write("### 📅 日期和时间")
    dc1, dc2 = st.columns([2, 1])
    with dc1:
        st.date_input("日期", key="diary_date", format="YYYY-MM-DD")
    with dc2:
        st.time_input("时间", key="diary_time", step=60)

    st.write("### 今天的心情")
    with st.container(key="mood_picker"):
        cols = st.columns(5)
        for i, (emoji, name) in enumerate(zip(MOOD_EMOJIS, MOOD_NAMES)):
            with cols[i]:
                is_sel = st.session_state.selected_mood == i + 1
                if st.button(emoji, key=f"mood_btn_{i}",
                             type="primary" if is_sel else "secondary",
                             use_container_width=True):
                    st.session_state.selected_mood = i + 1
                    st.rerun()
                st.markdown(
                    f"<div style='text-align:center;font-size:12px;"
                    f"color:var(--c-muted);margin-top:-4px'>{name}</div>",
                    unsafe_allow_html=True)

    content = st.text_area("日记内容", placeholder="写下你的心情和故事...",
                           height=250, key="diary_content")

    st.text_input("🏷️ 标签（用逗号分隔，可选）",
                  placeholder="例如：工作, 读书, 心情",
                  key="diary_tags")

    if editing_id and st.session_state.keep_images:
        st.write("📷 已有图片（点 ❌ 删除）：")
        keep = st.session_state.keep_images
        cols = st.columns(min(len(keep), 3))
        for i, img in enumerate(list(keep)):
            with cols[i % 3]:
                img_bytes = get_image(img)
                if img_bytes:
                    st.image(img_bytes, use_container_width=True)
                if st.button("❌ 删除这张", key=f"rmimg_{i}_{img}"):
                    st.session_state.keep_images.remove(img)
                    st.rerun()

    uploaded_files = st.file_uploader(
        "📷 贴图片（可选，支持多张）",
        type=["jpg", "jpeg", "png", "gif", "webp"],
        accept_multiple_files=True,
        key=f"diary_images_{st.session_state.uploader_key}",
    )
    if uploaded_files:
        st.write("预览：")
        cols = st.columns(min(len(uploaded_files), 3))
        for i, f in enumerate(uploaded_files):
            with cols[i % 3]:
                st.image(f, use_container_width=True)

    st.markdown(
        "<div class='kbd-hint'>💡 按 <b>Ctrl+Enter</b>（Mac 是 <b>⌘+Enter</b>）也能保存</div>",
        unsafe_allow_html=True,
    )
    btn_label = "💾 更新日记" if editing_id else "💾 保存日记"
    if st.button(btn_label, use_container_width=True, type="primary"):
        if not content.strip():
            st.warning("内容不能为空哦，写点什么吧~")
        else:
            tags = [t.strip() for t in st.session_state.diary_tags.split(",") if t.strip()]

            sel_d = st.session_state.diary_date
            if isinstance(sel_d, datetime):
                sel_d = sel_d.date()
            sel_t = st.session_state.diary_time
            if isinstance(sel_t, datetime):
                sel_t = sel_t.time()
            time_str = f"{sel_t.hour:02d}:{sel_t.minute:02d}"
            new_date_str = f"{sel_d.strftime('%Y-%m-%d')} {time_str}"

            with st.spinner("正在保存…"):
                if editing_id:
                    new_imgs = storage.save_image(uploaded_files, editing_id) if uploaded_files else []
                    final_imgs = st.session_state.keep_images + new_imgs

                    for i, e in enumerate(entries):
                        if e["id"] == editing_id:
                            entries[i].update({
                                "title": title.strip() or "无标题",
                                "mood": st.session_state.selected_mood,
                                "content": content.strip(),
                                "tags": tags,
                                "images": final_imgs,
                                "date": new_date_str,
                                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            })
                            break
                    save_all(entries)
                    st.session_state.editing_id = None
                    st.session_state.keep_images = []
                    st.session_state["diary_saved"] = True
                    st.session_state["clear_diary"] = True
                    st.rerun()
                else:
                    new_id = max((e["id"] for e in entries), default=0) + 1
                    imgs = storage.save_image(uploaded_files, new_id) if uploaded_files else []
                    entries.append({
                        "id": new_id,
                        "date": new_date_str,
                        "title": title.strip() or "无标题",
                        "mood": st.session_state.selected_mood,
                        "content": content.strip(),
                        "tags": tags,
                        "images": imgs,
                        "deleted": False,
                    })
                    save_all(entries)
                    st.session_state["diary_saved"] = True
                    st.session_state["clear_diary"] = True
                    st.rerun()

    components.html("""
    <script>
    (function() {
        const pw = window.parent;
        const handler = function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                const buttons = pw.document.querySelectorAll('button');
                for (const btn of buttons) {
                    const txt = btn.innerText || '';
                    if (txt.includes('保存日记') || txt.includes('更新日记')) {
                        e.preventDefault();
                        btn.click();
                        return;
                    }
                }
            }
        };
        if (pw.__diary_kb_handler) {
            pw.document.removeEventListener('keydown', pw.__diary_kb_handler, true);
        }
        pw.__diary_kb_handler = handler;
        pw.document.addEventListener('keydown', handler, true);
    })();
    </script>
    """, height=0)


# ==================================================
# 页面二：查看日记
# ==================================================
elif page == "📖 查看日记":
    st.subheader(f"共有 {len(active_entries)} 篇日记")

    if not active_entries:
        st.info("还没有日记，快去写第一篇吧！")
    else:
        c1, c2 = st.columns([2, 1])
        with c1:
            search = st.text_input("🔍 搜索关键词",
                                   placeholder="搜索标题或内容...",
                                   key="view_search")
        with c2:
            mood_filter = st.multiselect(
                "按心情筛选",
                options=[1, 2, 3, 4, 5],
                format_func=lambda x: f"{MOOD_EMOJIS[x-1]} {MOOD_NAMES[x-1]}",
                default=[], key="view_mood_filter")

        all_tags = collect_tags(active_entries)
        tag_filter = st.multiselect(
            "🏷️ 按标签筛选", options=all_tags, default=[],
            key="view_tag_filter") if all_tags else []

        filtered = sorted(
            active_entries,
            key=lambda e: (e.get("date", ""), e.get("id", 0)),
            reverse=True,
        )
        if mood_filter:
            filtered = [e for e in filtered if e.get("mood") in mood_filter]
        if tag_filter:
            filtered = [e for e in filtered
                        if any(t in e.get("tags", []) for t in tag_filter)]
        if search:
            filtered = [e for e in filtered
                        if search in e["content"] or search in e["title"]]

        st.caption(f"显示 {len(filtered)} 条")

        if not filtered:
            st.warning("没有符合条件的日记")
        else:
            for entry in filtered:
                mv = entry.get("mood", 3)
                me = MOOD_EMOJIS[mv - 1] if 1 <= mv <= 5 else "😐"
                with st.expander(f"📅 {entry['date']}　{me}　**{entry['title']}**"):
                    if entry.get("tags"):
                        st.markdown(
                            " ".join(f"<span class='tag-badge'>{t}</span>"
                                     for t in entry["tags"]),
                            unsafe_allow_html=True)
                    st.markdown(entry["content"])

                    imgs = entry.get("images", [])
                    if imgs:
                        st.write("📷 图片：")
                        cols = st.columns(min(len(imgs), 3))
                        for i, p in enumerate(imgs):
                            img_bytes = get_image(p)
                            if img_bytes:
                                with cols[i % 3]:
                                    st.image(img_bytes, use_container_width=True)

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("✏️ 编辑", key=f"edit_{entry['id']}",
                                     use_container_width=True):
                            st.session_state.editing_id = entry["id"]
                            st.session_state.diary_title = entry["title"]
                            st.session_state.diary_content = entry["content"]
                            st.session_state.selected_mood = entry.get("mood", 3)
                            st.session_state.diary_tags = ", ".join(entry.get("tags", []))
                            st.session_state.keep_images = list(entry.get("images", []))
                            try:
                                st.session_state.diary_date = datetime.strptime(
                                    entry["date"][:10], "%Y-%m-%d").date()
                            except Exception:
                                st.session_state.diary_date = date.today()
                            try:
                                st.session_state.diary_time = datetime.strptime(
                                    entry["date"][11:16], "%H:%M").time()
                            except Exception:
                                st.session_state.diary_time = datetime.now().time().replace(
                                    second=0, microsecond=0)
                            st.session_state.uploader_key += 1
                            st.session_state.pending_nav = "✍️ 写日记"
                            st.rerun()
                    with bc2:
                        if st.button("🗑️ 删除", key=f"del_{entry['id']}",
                                     use_container_width=True):
                            st.session_state.pending_delete_id = entry["id"]
                            st.rerun()

                    if st.session_state.get("pending_delete_id") == entry["id"]:
                        st.warning(f"确定要删除《{entry['title']}》吗？删除后可在回收站恢复。")
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            if st.button("✅ 确认删除",
                                         key=f"confirm_del_{entry['id']}",
                                         type="primary", use_container_width=True):
                                for i, e in enumerate(entries):
                                    if e["id"] == entry["id"]:
                                        entries[i]["deleted"] = True
                                        entries[i]["deleted_at"] = datetime.now().strftime(
                                            "%Y-%m-%d %H:%M")
                                        break
                                save_all(entries)
                                st.session_state.pending_delete_id = None
                                st.rerun()
                        with cc2:
                            if st.button("❌ 取消",
                                         key=f"cancel_del_{entry['id']}",
                                         use_container_width=True):
                                st.session_state.pending_delete_id = None
                                st.rerun()


# ==================================================
# 页面三：日历视图
# ==================================================
elif page == "📅 日历视图":
    st.subheader("📅 日历视图")

    streak = calc_streak(entries)
    this_month = sum(
        1 for e in active_entries
        if e["date"][:7] == datetime.now().strftime("%Y-%m")
    )
    stat_cols = st.columns(4, gap="small")
    stats = [
        (len(active_entries), "📚 总日记"),
        (this_month, "📝 本月"),
        (f"{streak}天", "🔥 连续"),
        (len(deleted_entries), "🗑️ 回收站"),
    ]
    for i, (num, label) in enumerate(stats):
        with stat_cols[i]:
            st.markdown(
                f"<div class='stat-card'><div class='num'>{num}</div>"
                f"<div class='label'>{label}</div></div>",
                unsafe_allow_html=True,
            )

    st.write("")

    c1, c2, c3, c4, c5 = st.columns([1, 1, 3, 1, 1])
    with c1:
        if st.button("◀", key="prev_m", use_container_width=True):
            if st.session_state.cal_month == 1:
                st.session_state.cal_month = 12
                st.session_state.cal_year -= 1
            else:
                st.session_state.cal_month -= 1
            st.rerun()
    with c3:
        st.markdown(
            f"<div style='text-align:center;font-size:20px;font-weight:600;"
            f"padding-top:6px'>{st.session_state.cal_year} 年 "
            f"{st.session_state.cal_month} 月</div>",
            unsafe_allow_html=True)
    with c5:
        if st.button("▶", key="next_m", use_container_width=True):
            if st.session_state.cal_month == 12:
                st.session_state.cal_month = 1
                st.session_state.cal_year += 1
            else:
                st.session_state.cal_month += 1
            st.rerun()

    y, m = st.session_state.cal_year, st.session_state.cal_month
    date_map = {}
    for e in active_entries:
        try:
            d = datetime.strptime(e["date"][:10], "%Y-%m-%d").date()
            if d.year == y and d.month == m:
                date_map.setdefault(d, []).append(e)
        except Exception:
            pass

    day_names = ["日", "一", "二", "三", "四", "五", "六"]
    head = st.columns(7, gap="small")
    for i, n in enumerate(day_names):
        with head[i]:
            st.markdown(
                f"<div style='text-align:center;color:var(--c-muted);"
                f"font-size:12px;margin-bottom:4px'>{n}</div>",
                unsafe_allow_html=True)

    grid = cal_mod.Calendar(firstweekday=6).monthdayscalendar(y, m)
    today = date.today()
    for week in grid:
        cols = st.columns(7, gap="small")
        for i, day in enumerate(week):
            with cols[i]:
                if day == 0:
                    st.markdown(
                        "<div style='height:40px'></div>",
                        unsafe_allow_html=True)
                else:
                    d = date(y, m, day)
                    cnt = len(date_map.get(d, []))
                    if cnt > 0:
                        lvl = min(cnt, 3)
                        if st.button(
                            " ",
                            key=f"calL{lvl}_{d.isoformat()}",
                            use_container_width=True,
                            help=f"{d.strftime('%m-%d')} · {cnt} 篇",
                        ):
                            st.session_state.cal_selected = d.isoformat()
                            st.rerun()
                    else:
                        prefix = "calEtoday" if d == today else "calE"
                        if st.button(
                            " ",
                            key=f"{prefix}_{d.isoformat()}",
                            use_container_width=True,
                            help=f"{d.strftime('%m-%d')} · 没有日记",
                        ):
                            st.session_state.cal_selected = d.isoformat()
                            st.rerun()

    st.markdown("""
    <div style='display:flex;justify-content:flex-end;align-items:center;
    gap:4px;font-size:11px;color:var(--c-muted);margin-top:8px'>
    <span style='margin-right:4px'>少</span>
    <span style='width:12px;height:12px;background:var(--c-soft-bg);border-radius:3px'></span>
    <span style='width:12px;height:12px;background:rgba(var(--c-accent-rgb),0.30);border-radius:3px'></span>
    <span style='width:12px;height:12px;background:rgba(var(--c-accent-rgb),0.60);border-radius:3px'></span>
    <span style='width:12px;height:12px;background:rgba(var(--c-accent-rgb),0.95);border-radius:3px'></span>
    <span style='margin-left:4px'>多</span>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    sel = st.session_state.get("cal_selected")
    if sel:
        try:
            sd = datetime.strptime(sel, "%Y-%m-%d").date()
        except Exception:
            sd = None
        if sd:
            if sd in date_map:
                st.write(f"### {sd.strftime('%Y-%m-%d')}（{len(date_map[sd])} 篇）")
                for e in date_map[sd]:
                    mv = e.get("mood", 3)
                    me = MOOD_EMOJIS[mv - 1] if 1 <= mv <= 5 else "😐"
                    with st.expander(f"{me}　**{e['title']}**　{e['date'][11:]}"):
                        if e.get("tags"):
                            st.markdown(
                                " ".join(f"<span class='tag-badge'>{t}</span>"
                                         for t in e["tags"]),
                                unsafe_allow_html=True)
                        st.markdown(e["content"])
                        imgs = e.get("images", [])
                        if imgs:
                            cols = st.columns(min(len(imgs), 3))
                            for i, p in enumerate(imgs):
                                img_bytes = get_image(p)
                                if img_bytes:
                                    with cols[i % 3]:
                                        st.image(img_bytes, use_container_width=True)
            else:
                st.info(f"{sd.strftime('%Y-%m-%d')} 还没有日记")

            has_diary = sd in date_map
            btn_label = "✍️ 再写一篇这天的日记" if has_diary else "✍️ 补写这天的日记"
            if st.button(btn_label,
                         type="secondary" if has_diary else "primary",
                         use_container_width=True,
                         key=f"supplement_{sd.isoformat()}"):
                st.session_state.diary_date = sd
                st.session_state.diary_time = datetime.now().time().replace(
                    second=0, microsecond=0)
                st.session_state.editing_id = None
                st.session_state.diary_title = ""
                st.session_state.diary_content = ""
                st.session_state.diary_tags = ""
                st.session_state.selected_mood = 3
                st.session_state.keep_images = []
                st.session_state.uploader_key += 1
                st.session_state.pending_nav = "✍️ 写日记"
                st.rerun()
    else:
        st.caption("👆 点击任意格子查看 / 补写当天的日记")


# ==================================================
# 页面四：总结日记
# ==================================================
elif page == "🧠 总结日记":
    st.subheader("🧠 日记总结")
    st.caption("挑出你写得最有代表性的句子，帮你回顾这段时间。")

    if not active_entries:
        st.info("还没有日记，先去写几篇吧~")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            sum_mood = st.multiselect(
                "按心情筛选", options=[1, 2, 3, 4, 5],
                format_func=lambda x: f"{MOOD_EMOJIS[x-1]} {MOOD_NAMES[x-1]}",
                default=[], key="sum_mood")
        with c2:
            all_tags = collect_tags(active_entries)
            sum_tags = st.multiselect("按标签筛选", all_tags,
                                      default=[], key="sum_tags")
        with c3:
            days = st.slider("最近 N 天（0 = 全部）", 0, 365, 0, key="sum_days")

        filtered = active_entries
        if sum_mood:
            filtered = [e for e in filtered if e.get("mood") in sum_mood]
        if sum_tags:
            filtered = [e for e in filtered
                        if any(t in e.get("tags", []) for t in sum_tags)]
        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)
            tmp = []
            for e in filtered:
                try:
                    if datetime.strptime(e["date"][:10], "%Y-%m-%d") >= cutoff:
                        tmp.append(e)
                except Exception:
                    pass
            filtered = tmp

        st.caption(f"将总结 {len(filtered)} 篇日记")
        top_n = st.slider("摘要句数", 3, 15, 6, key="sum_topn")

        if st.button("✨ 生成总结", use_container_width=True, type="primary"):
            if not filtered:
                st.warning("没有符合条件的日记")
            else:
                texts = [e["content"] for e in filtered]
                summary = summarize_texts(texts, top_n=top_n)
                if summary:
                    st.write("### 📝 摘要")
                    for i, s in enumerate(summary, 1):
                        st.markdown(f"**{i}.** {s}。")

                kws = top_keywords(texts, k=12)
                if kws:
                    st.write("### 🔑 高频关键词")
                    st.markdown("　".join(f"`{w}`" for w in kws))

                st.write("### 📊 心情分布")
                mood_counts = Counter(e.get("mood", 3) for e in filtered)
                chart = {MOOD_NAMES[i-1]: mood_counts.get(i, 0)
                         for i in range(1, 6)}
                st.bar_chart(chart, height=200)

                with st.expander("📋 参与总结的日记"):
                    for e in sorted(filtered,
                                    key=lambda x: (x.get("date", ""), x.get("id", 0)),
                                    reverse=True):
                        mv = e.get("mood", 3)
                        me = MOOD_EMOJIS[mv-1] if 1 <= mv <= 5 else "😐"
                        st.markdown(f"**{e['date']}　{me}　{e['title']}**")
                        st.caption(e["content"][:80] +
                                   ("..." if len(e["content"]) > 80 else ""))


# ==================================================
# 页面五：回收站
# ==================================================
elif page == "🗑️ 回收站":
    st.subheader(f"🗑️ 回收站（{len(deleted_entries)} 篇）")
    st.caption(f"🗓️ 回收站里的日记会在 **{TRASH_RETENTION_DAYS} 天**后自动永久删除")

    if not deleted_entries:
        st.info("回收站是空的 ✨")
    else:
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("♻️ 全部恢复", use_container_width=True):
                for e in entries:
                    if e.get("deleted"):
                        e["deleted"] = False
                        e["deleted_at"] = None
                save_all(entries)
                st.success("已全部恢复")
                st.rerun()
        with c2:
            if st.button("🔥 清空回收站（不可恢复）",
                         use_container_width=True, type="primary"):
                st.session_state.confirm_empty_trash = True

        if st.session_state.get("confirm_empty_trash"):
            st.error("⚠️ 确定要永久删除回收站里的所有日记吗？图片也会一起删掉。")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("✅ 确认清空", type="primary",
                             use_container_width=True):
                    with st.spinner("正在清空…"):
                        for e in entries:
                            if e.get("deleted"):
                                for p in e.get("images", []):
                                    storage.delete_image(p)
                        entries = [e for e in entries if not e.get("deleted")]
                        save_all(entries)
                    st.session_state.confirm_empty_trash = False
                    st.success("回收站已清空")
                    st.rerun()
            with cc2:
                if st.button("❌ 取消", use_container_width=True):
                    st.session_state.confirm_empty_trash = False
                    st.rerun()

        st.divider()

        for entry in deleted_entries[::-1]:
            eid = entry["id"]
            mv = entry.get("mood", 3)
            me = MOOD_EMOJIS[mv-1] if 1 <= mv <= 5 else "😐"
            with st.container(border=True):
                c_info, c1, c2 = st.columns([5, 1, 1])
                with c_info:
                    st.markdown(
                        f"**{entry['date']}**　{me}　**{entry['title']}**")
                    if entry.get("deleted_at"):
                        try:
                            dt = datetime.strptime(entry["deleted_at"], "%Y-%m-%d %H:%M")
                            days_left = TRASH_RETENTION_DAYS - (datetime.now() - dt).days
                            if days_left <= 3:
                                color, note = "#e74c3c", f"⚠️ 还剩 {days_left} 天自动清除"
                            elif days_left <= 7:
                                color, note = "#e67e22", f"还剩 {days_left} 天自动清除"
                            else:
                                color, note = "var(--c-muted)", f"还剩 {days_left} 天自动清除"
                            st.caption(f"删除于 {entry['deleted_at']}")
                            st.markdown(
                                f"<div style='font-size:11px;color:{color}'>"
                                f"{note}</div>",
                                unsafe_allow_html=True,
                            )
                        except Exception:
                            st.caption(f"删除于 {entry['deleted_at']}")
                    preview = entry["content"][:60]
                    if len(entry["content"]) > 60:
                        preview += "..."
                    st.caption(preview)
                with c1:
                    if st.button("♻️ 恢复", key=f"restore_{eid}"):
                        for e in entries:
                            if e["id"] == eid:
                                e["deleted"] = False
                                e["deleted_at"] = None
                                break
                        save_all(entries)
                        st.rerun()
                with c2:
                    if st.button("🔥", key=f"purge_{eid}", help="永久删除"):
                        with st.spinner("删除中…"):
                            for e in entries:
                                if e["id"] == eid:
                                    for p in e.get("images", []):
                                        storage.delete_image(p)
                                    break
                            entries = [e for e in entries if e["id"] != eid]
                            save_all(entries)
                        st.rerun()


# ==================================================
# 页面六：设置
# ==================================================
elif page == "⚙️ 设置":
    st.subheader("⚙️ 设置")

    # ---- 存储状态 ----
    st.write("### ☁️ 存储状态")
    ok, msg = check_connection()
    if ok:
        st.success(msg)
    else:
        st.error(msg)
    if is_remote():
        st.caption("数据实时同步到你的 GitHub 私有仓库，任何设备访问都是同一份。")
    else:
        st.caption("当前使用本地文件（diary.json + images/）。"
                   "配置 GitHub 后会自动切到云端。")

    st.divider()

    # ---- 备份导出 ----
    st.write("### 💾 数据备份")
    st.caption("下载一份包含所有日记 + 图片的 zip 压缩包。")
    if active_entries or deleted_entries:
        if st.button("📦 生成备份", use_container_width=True):
            with st.spinner("正在打包（图片多时会慢一点）…"):
                zip_bytes = storage.create_backup_zip(entries)
            fname = f"diary_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            st.download_button(
                "📥 点击下载备份 (.zip)",
                data=zip_bytes, file_name=fname, mime="application/zip",
                use_container_width=True)
    else:
        st.info("还没有日记可以备份")

    st.divider()

    # ---- 导入 ----
    st.write("### 📤 数据恢复")
    st.warning("⚠️ 导入会**覆盖**当前所有日记和图片（请谨慎操作）")
    up = st.file_uploader("上传备份 zip", type=["zip"], key="import_zip")
    if up is not None:
        if st.button("确认导入并覆盖", type="primary", use_container_width=True):
            with st.spinner("正在导入…"):
                try:
                    n = storage.import_backup_zip(up)
                    refresh_all()
                    st.success(f"已导入 {n} 篇日记！")
                    st.rerun()
                except Exception as ex:
                    st.error(f"导入失败：{ex}")

    st.divider()

    # ---- 统计 ----
    st.write("### 📊 使用统计")
    if active_entries:
        total_words = sum(len(e["content"]) for e in active_entries)
        total_imgs = sum(len(e.get("images", [])) for e in active_entries)
        first_date = min(e["date"][:10] for e in active_entries)
        st.markdown(f"""
- 总日记数：**{len(active_entries)}** 篇
- 回收站：**{len(deleted_entries)}** 篇
- 总字数：**{total_words:,}** 字
- 总图片：**{total_imgs}** 张
- 连续记录：**{streak}** 天
- 第一篇日记：**{first_date}**
""")
    else:
        st.info("暂无数据")

    st.divider()

    # ---- 运行环境 ----
    st.write("### 🔧 运行环境")
    st.markdown(f"""
- 存储模式：**{"GitHub 云端" if is_remote() else "本地文件"}**
- 中文分词（jieba）：{"✅ 已安装" if _HAS_JIEBA else "❌ 未安装（摘要质量会降低）"}
- 图片压缩（Pillow）：{"✅ 已安装" if _HAS_PIL else "❌ 未安装（图片不压缩）"}
""")
    if not _HAS_JIEBA or not _HAS_PIL:
        st.code("pip install jieba pillow", language="bash")

    st.divider()

    # ---- 退出登录 ----
    if st.session_state.get("_authed"):
        if st.button("🚪 退出登录", use_container_width=True):
            st.session_state._authed = False
            st.rerun()
