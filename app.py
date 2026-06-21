import os
import sqlite3
import base64
import uuid
from datetime import datetime

import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ========== 配置（从环境变量读取）==========
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-image-1")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "standard")
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "3"))
ADMIN_CODE = os.getenv("ADMIN_CODE", "ADMIN2024")  # 管理员面板密码

DB_PATH = "users.db"

# ========== 数据库初始化 ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            used_count INTEGER DEFAULT 0,
            is_unlimited INTEGER DEFAULT 0,
            first_use DATE,
            last_use DATE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS activation_codes (
            code TEXT PRIMARY KEY,
            used_by TEXT DEFAULT NULL,
            used_at DATE DEFAULT NULL,
            created_at DATE DEFAULT CURRENT_DATE
        )
    ''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id, used_count, is_unlimited, first_use FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "used_count": row[1], "is_unlimited": row[2], "first_use": row[3]}
    return None

def create_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    c.execute('''
        INSERT OR IGNORE INTO users (user_id, used_count, is_unlimited, first_use, last_use)
        VALUES (?, 0, 0, ?, ?)
    ''', (user_id, today, today))
    conn.commit()
    conn.close()

def increment_usage(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    c.execute('UPDATE users SET used_count = used_count + 1, last_use = ? WHERE user_id = ?', (today, user_id))
    conn.commit()
    conn.close()

def can_generate(user_id):
    user = get_user(user_id)
    if not user:
        return True, "新用户"
    if user["is_unlimited"] == 1:
        return True, "无限用户"
    if user["used_count"] >= FREE_LIMIT:
        return False, f"免费次数已用完（{FREE_LIMIT}次），请购买激活码解锁无限生成"
    return True, f"剩余 {FREE_LIMIT - user['used_count']} 次"

def activate_user(user_id, code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code FROM activation_codes WHERE code = ? AND used_by IS NULL', (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "❌ 激活码无效或已被使用"
    today = datetime.now().date().isoformat()
    c.execute('UPDATE activation_codes SET used_by = ?, used_at = ? WHERE code = ?', (user_id, today, code))
    c.execute('UPDATE users SET is_unlimited = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return True, "🎉 激活成功！你现在可以无限次生成图像了！"

def generate_activation_code():
    code = str(uuid.uuid4())[:8].upper()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO activation_codes (code) VALUES (?)', (code,))
    conn.commit()
    conn.close()
    return code

def generate_image(prompt: str):
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    try:
        response = client.images.generate(
            model=OPENAI_MODEL,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
            response_format="b64_json"
        )
        return True, response.data[0].b64_json
    except Exception as e:
        return False, str(e)

def get_user_id():
    if "user_id" not in st.session_state:
        if "user_id" in st.query_params:
            st.session_state.user_id = st.query_params["user_id"]
        else:
            st.session_state.user_id = str(uuid.uuid4())
    return st.session_state.user_id

# ========== Streamlit 页面 ==========
def main():
    st.set_page_config(page_title="AI 图像生成器", page_icon="🎨", layout="centered")
    init_db()
    user_id = get_user_id()
    create_user(user_id)
    user = get_user(user_id)

    # ---------- 侧边栏：用户信息 & 激活 ----------
    with st.sidebar:
        st.title("👤 我的账户")
        if user["is_unlimited"] == 1:
            st.success("🔓 无限模式（已激活）")
            used_display = "∞"
        else:
            remaining = FREE_LIMIT - user["used_count"]
            if remaining > 0:
                st.info(f"📊 免费剩余：{remaining} 次")
            else:
                st.warning("⚠️ 免费次数已用完")
            used_display = str(user["used_count"])
        st.caption(f"已使用：{used_display} 次")
        st.caption(f"首次使用：{user['first_use']}")
        st.divider()
        st.markdown("### 🔑 激活码")
        code_input = st.text_input("输入激活码", placeholder="例如：A7F3B9D1")
        if st.button("激活", use_container_width=True):
            if code_input:
                success, msg = activate_user(user_id, code_input.strip().upper())
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("请输入激活码")
        st.divider()
        st.caption("💡 免费用户可生成 3 次，之后需激活码解锁无限模式")

    # ---------- 主界面 ----------
    st.title("🎨 AI 图像生成器")
    st.markdown("输入文字描述，AI 将为你生成一张独特的图像")

    can, msg = can_generate(user_id)
    if not can:
        st.error(f"❌ {msg}")
        st.info("请在左侧输入激活码解锁无限生成，或联系管理员购买")
        st.stop()

    prompt = st.text_area(
        "📝 描述你想要生成的图像",
        placeholder="例如：一只可爱的橘猫坐在月亮上，星空背景，梦幻风格",
        height=100
    )

    with st.expander("⚙️ 高级选项"):
        col1, col2 = st.columns(2)
        with col1:
            size = st.selectbox("图片尺寸", ["1024x1024", "1024x1536", "1536x1024"], index=0)
        with col2:
            quality = st.selectbox("图片质量", ["standard", "hd"], index=0)

    if st.button("🚀 生成图像", type="primary", use_container_width=True):
        if not prompt.strip():
            st.warning("请输入图像描述")
            st.stop()
        can, msg = can_generate(user_id)
        if not can:
            st.error(f"❌ {msg}")
            st.stop()
        with st.spinner("🎨 AI 正在创作中，请稍候..."):
            success, result = generate_image(prompt)
        if not success:
            st.error(f"❌ 生成失败：{result}")
            st.stop()
        increment_usage(user_id)
        try:
            image_data = base64.b64decode(result)
            st.image(image_data, caption=f"📝 {prompt[:80]}{'...' if len(prompt) > 80 else ''}", use_container_width=True)
            user_updated = get_user(user_id)
            if user_updated["is_unlimited"] == 0:
                remaining = FREE_LIMIT - user_updated["used_count"]
                if remaining > 0:
                    st.success(f"✅ 生成成功！剩余免费次数：{remaining}")
                else:
                    st.warning("⚠️ 这是最后一次免费生成，请购买激活码解锁无限模式")
            else:
                st.success("✅ 生成成功！无限模式已激活")
            st.download_button(
                label="📥 下载图片",
                data=image_data,
                file_name=f"ai_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                mime="image/png"
            )
        except Exception as e:
            st.error(f"❌ 显示图片失败：{e}")

    st.divider()
    with st.expander("📖 使用说明"):
        st.markdown("""
        **1. 免费使用** – 新用户默认获得 **3 次** 免费生成机会  
        **2. 解锁无限模式** – 在左侧输入激活码，点击「激活」即可永久无限生成  
        **3. 获取激活码** – 联系管理员购买（联系方式见下方）  
        **4. 提示词技巧** – 描述越详细，效果越好，建议包含主体、环境、风格
        """)

    # ---------- 管理员面板 ----------
    with st.expander("🔐 管理员面板"):
        admin_pwd = st.text_input("管理员密码", type="password")
        if admin_pwd == ADMIN_CODE:
            st.success("✅ 已验证")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("生成 1 个激活码"):
                    code = generate_activation_code()
                    st.success(f"✅ 新激活码：`{code}`")
            with col2:
                num = st.number_input("数量", min_value=1, max_value=20, value=5)
                if st.button(f"生成 {num} 个激活码"):
                    codes = []
                    for _ in range(num):
                        codes.append(generate_activation_code())
                    st.success("✅ 已生成：\n\n" + "\n".join([f"`{c}`" for c in codes]))
            # 统计信息
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM users')
            total_users = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM users WHERE is_unlimited = 1')
            unlimited_users = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM activation_codes WHERE used_by IS NULL')
            unused_codes = c.fetchone()[0]
            conn.close()
            st.divider()
            st.metric("👤 总用户", total_users)
            st.metric("🔓 无限用户", unlimited_users)
            st.metric("🔑 未使用激活码", unused_codes)
        elif admin_pwd:
            st.error("❌ 密码错误")

if __name__ == "__main__":
    main()