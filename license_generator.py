# -*- coding: utf-8 -*-
"""Lucky Make 激活码生成器（简化方案：机器码绑定 + 共享密钥 HMAC + 有效期）

面向「卖家 / 开发者」的独立 Streamlit 工具，可单独部署到云：
  1) 输入客户机器码 + 有效期（小时），本地计算生成激活码（非明文，Base64 编码）；
  2) 校验一枚激活码：解析机器码 / 有效时长 / 到期时间 / 是否永久 / 机器码是否匹配。

方案要点（与桌面程序 lucky_make_main.py 完全一致）：
  - 不使用公钥/私钥，激活码 = Base64( 机器码|小时数|HMAC-SHA256签名 )；
  - 有效期起算时间固定为 2026-09-01 00:00（北京时间），到期 = 起算 + 小时数；
  - 机器码匹配且有效时长 >= 0xFFFFFFFF（魔法值，≈49万年）→ 主程序视为永久激活（不判断时间，可离线运行）；
  - 两端 ACTIVATION_SECRET 必须一致，更改时请同步修改主程序并重新打包。

运行：  streamlit run license_generator.py
依赖：  streamlit>=1.61
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import math
from datetime import datetime, time, timedelta, timezone

import streamlit as st

# ---------------------------------------------------------------------------
# 与桌面程序 lucky_make_main.py 保持一致的常量（切勿单独修改其一）
# ---------------------------------------------------------------------------
ACTIVATION_SECRET = "LM-Act-2026-Secret-#K7q9"
EPOCH_START = datetime(2026, 9, 1, 0, 0, 0)          # 固定起算时间（北京时间）
PERMANENT_HOURS_THRESHOLD = 0xFFFFFFFF                # >= 该魔法值（≈49万年）视为永久激活
PERMANENT_HOURS = 0xFFFFFFFF                          # 「永久激活」按钮写入的魔法时长
BEIJING_TZ = timezone(timedelta(hours=8), "北京时间")

# 访问口令：云端在 Streamlit App Secrets 配置 ACCESS_PASSWORD 覆盖；
# 未配置时回退到下面内置默认口令（仅供本地测试，部署到云端务必覆盖）。
DEFAULT_ACCESS_PASSWORD = "LuckyMake#2026"


# ---------------------------------------------------------------------------
# 纯函数：与桌面程序的验签逻辑保持完全一致
# ---------------------------------------------------------------------------
def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def normalize_machine_code(code: str) -> str:
    # 统一机器码：仅保留十六进制字符并大写，每 4 位一组用 - 连接
    raw = "".join(ch for ch in str(code).strip().upper() if ch in "0123456789ABCDEF")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def _hmac_sig(payload: str) -> str:
    # 共享密钥 HMAC-SHA256，取前 16 位十六进制作为签名
    return hmac.new(ACTIVATION_SECRET.encode("utf-8"), payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:16]


def make_license(machine_code: str, hours: int) -> str:
    # 生成激活码：Base64( 机器码|小时数|签名 )
    payload = f"{normalize_machine_code(machine_code)}|{int(hours)}"
    return _b64e(f"{payload}|{_hmac_sig(payload)}".encode("utf-8"))


def parse_license(license_str: str):
    """解析并校验激活码，返回 (machine_code, hours)；无效或被篡改返回 None。"""
    try:
        raw = _b64d((license_str or "").strip()).decode("utf-8")
    except Exception:
        return None
    parts = raw.split("|")
    if len(parts) != 3:
        return None
    mc, hours_s, sig = parts
    if not mc or _hmac_sig(f"{mc}|{hours_s}") != sig:
        return None
    try:
        hours = int(hours_s)
    except Exception:
        return None
    if hours < 0:
        return None
    return mc, hours


def license_expiry(hours: int) -> datetime:
    # 到期时间（北京时间）= 固定起算时间 + 有效时长
    return EPOCH_START.replace(tzinfo=BEIJING_TZ) + timedelta(hours=hours)


def hours_since_epoch(now_bj: datetime) -> int:
    # 自固定起算点已过去的小时数（用于提示卖家换算有效期）
    return int((now_bj - EPOCH_START.replace(tzinfo=BEIJING_TZ)).total_seconds() // 3600)


def expiry_to_hours(exp_bj: datetime) -> int:
    # 由到期时间（北京时间）换算自固定起算点的有效小时数（向上取整，至少 1）
    delta = (exp_bj - EPOCH_START.replace(tzinfo=BEIJING_TZ)).total_seconds() / 3600
    return max(1, math.ceil(delta))


def describe_license(license_str: str, machine_code: str = "") -> tuple[bool, str]:
    """校验并描述一枚激活码，返回 (是否有效, Markdown 详情)。"""
    parsed = parse_license(license_str)
    if parsed is None:
        return False, "激活码无效或已被篡改（HMAC 签名校验失败）。"
    mc, hours = parsed
    md = [f"- **机器码**：`{mc}`"]
    if hours >= PERMANENT_HOURS_THRESHOLD:
        md.append("- **有效时长**：♾️ 永久（时长标记 0xFFFFFFFF）")
        md.append("- **类型**：🟢 永久激活（主程序不再判断有效期，可离线运行）")
    else:
        md.append(f"- **有效时长**：{hours} 小时")
        exp = license_expiry(hours)
        md.append("- **类型**：⏳ 限时激活")
        md.append(f"- **到期时间**：{exp:%Y-%m-%d %H:%M}（北京时间，自 2026-09-01 00:00 起算）")
    if machine_code.strip():
        if normalize_machine_code(machine_code) == mc:
            md.append("- **机器码匹配**：✅ 与所填一致")
        else:
            md.append(f"- **机器码匹配**：❌ 与所填 `{normalize_machine_code(machine_code)}` 不一致")
    return True, "\n".join(md)


def issued_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["time", "machine", "hours", "type"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _runtime_active() -> bool:
    # 在 Streamlit 运行时执行 UI；被普通 import（如测试）时跳过，仅暴露纯函数
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return True


def _access_password() -> tuple[str, bool]:
    # 生效访问口令：优先云端 st.secrets["ACCESS_PASSWORD"]，否则回退内置默认。
    # 返回 (口令, 是否来自 Secrets)。
    try:
        val = str(st.secrets.get("ACCESS_PASSWORD", "")).strip()
    except Exception:
        val = ""
    if val:
        return val, True
    return DEFAULT_ACCESS_PASSWORD, False


# ---------------------------------------------------------------------------
# 页面 UI（直接脚本）
# ---------------------------------------------------------------------------
if _runtime_active():
    st.set_page_config(page_title="Lucky Make 激活码生成器", page_icon=":material/key:", layout="wide")

    # ---- 访问口令门：未通过验证则不渲染任何生成器内容 ----
    _pwd, _from_secret = _access_password()
    st.session_state.setdefault("authed", False)
    if not st.session_state["authed"]:
        st.title("\U0001F510 访问验证")
        st.caption("本工具用于签发激活码，请输入卖家访问口令后继续。")
        with st.form("auth_form"):
            _entered = st.text_input("访问口令", type="password", placeholder="请输入口令")
            _go = st.form_submit_button("进入", icon=":material/lock_open:", type="primary")
        if _go:
            if _entered.strip() == _pwd:
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("口令错误，无法访问。", icon=":material/block:")
        st.stop()

    # ---- 已通过验证 ----
    st.session_state.setdefault("issued", [])
    tcol, bcol = st.columns([6, 1], vertical_alignment="center")
    with tcol:
        st.title("Lucky Make 激活码生成器")
    with bcol:
        if st.button("锁定", icon=":material/lock:", width="stretch", help="退出登录，重新需要口令"):
            st.session_state["authed"] = False
            st.rerun()
    st.caption("简化方案 · 机器码绑定 + 共享密钥 HMAC + 有效期（自 2026-09-01 00:00 北京时间起算）")
    if not _from_secret:
        st.warning(
            "当前使用**内置默认口令**，仅供本地测试。部署到 Streamlit Cloud 时，请在 "
            "App → Settings → Secrets 配置 `ACCESS_PASSWORD` 覆盖它，否则默认口令即公开。",
            icon=":material/warning:",
        )

    tab_gen, tab_verify, tab_help = st.tabs(["生成激活码", "校验激活码", "使用说明"])

    # ------------------------------------------------------------------ 生成
    with tab_gen:
        st.subheader("输入机器码与到期日期，生成激活码")
        now_bj = datetime.now(BEIJING_TZ)
        since = hours_since_epoch(now_bj)
        st.info(
            f"当前北京时间约 **{now_bj:%Y-%m-%d %H:%M}**，"
            f"自固定起算点（2026-09-01 00:00）已过去约 **{since}** 小时。",
            icon=":material/schedule:",
        )

        with st.form("gen_form"):
            machine = st.text_input("机器码", placeholder="例如 A1B2-C3D4-E5F6-7890-ABCD")

            st.markdown("**⏳ 限时激活** — 选择到期日期与时刻（北京时间），自动换算有效时长：")
            col_d, col_t = st.columns([2, 1])
            with col_d:
                exp_date = st.date_input(
                    "到期日期", value=(now_bj + timedelta(days=7)).date(),
                    min_value=EPOCH_START.date(),
                )
            with col_t:
                exp_time = st.time_input("到期时刻", value=time(23, 59), step=60)
            st.caption(
                "限时激活码按所选到期时间判断有效期，任意日期均可（不会被误判为永久）；"
                "如需永久有效，请改用下方「生成永久激活码」。"
            )
            btn_limited = st.form_submit_button(
                "生成限时激活码", icon=":material/event:", type="primary", width="stretch",
            )

            st.divider()
            st.markdown("**♾️ 永久激活** — 无需选择到期日期，机器码匹配即永久有效（可离线运行）：")
            btn_perm = st.form_submit_button(
                "生成永久激活码", icon=":material/all_inclusive:", width="stretch",
            )

        if btn_limited or btn_perm:
            if not machine.strip():
                st.error("请填写客户机器码。", icon=":material/error:")
            else:
                if btn_perm:
                    hours = PERMANENT_HOURS
                else:
                    exp_bj = datetime.combine(exp_date, exp_time, tzinfo=BEIJING_TZ)
                    hours = expiry_to_hours(exp_bj)
                lic = make_license(machine, hours)
                mc = normalize_machine_code(machine)
                st.success("激活码已生成，请发送给客户：", icon=":material/check_circle:")
                st.code(lic, language=None, wrap_lines=True)

                if hours >= PERMANENT_HOURS_THRESHOLD:
                    st.warning(
                        "永久激活码（时长标记 0xFFFFFFFF），"
                        "主程序不再判断有效期，机器码匹配即永久有效，可离线运行。",
                        icon=":material/all_inclusive:",
                    )
                else:
                    exp = license_expiry(hours)
                    if exp < now_bj:
                        st.error(
                            f"注意：所选到期时间 {exp:%Y-%m-%d %H:%M}（北京时间）早于当前时间，"
                            "生成即已过期，请重新选择更晚的到期日期。",
                            icon=":material/warning:",
                        )
                    else:
                        st.info(
                            f"限时激活：到期 **{exp:%Y-%m-%d %H:%M}**（北京时间），有效时长 {hours} 小时。",
                            icon=":material/event:",
                        )

                st.download_button(
                    "下载激活码 txt", lic, file_name=f"license_{mc}.txt",
                    mime="text/plain", icon=":material/download:", width="content",
                )
                st.session_state["issued"].insert(0, {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "machine": mc,
                    "hours": hours,
                    "type": "永久" if hours >= PERMANENT_HOURS_THRESHOLD else "限时",
                })

        if st.session_state["issued"]:
            st.markdown("**本次会话签发记录**")
            st.dataframe(st.session_state["issued"], hide_index=True)
            st.download_button(
                "下载签发记录 CSV", issued_to_csv(st.session_state["issued"]),
                file_name="issued_log.csv", mime="text/csv",
                icon=":material/download:", width="content",
            )

    # ------------------------------------------------------------------ 校验
    with tab_verify:
        st.subheader("校验一枚激活码")
        with st.form("verify_form"):
            lic_in = st.text_area("激活码", height=100, placeholder="粘贴激活码")
            mc_in = st.text_input("机器码（可选，用于校验绑定）", placeholder="留空则只解析激活码")
            vsubmitted = st.form_submit_button("校验", icon=":material/search:", type="primary")

        if vsubmitted:
            if not lic_in.strip():
                st.error("请填写激活码。", icon=":material/error:")
            else:
                ok, detail = describe_license(lic_in, mc_in)
                if ok:
                    st.success("激活码有效（签名校验通过）：", icon=":material/check_circle:")
                    st.markdown(detail)
                else:
                    st.error(detail, icon=":material/block:")

    # ------------------------------------------------------------------ 说明
    with tab_help:
        st.subheader("使用说明")
        st.markdown(
            f"""
**激活码格式**：`Base64( 机器码 | 有效小时数 | HMAC-SHA256签名 )`，非明文，签名由共享密钥本地计算。

**生成方式**
- ⏳ 限时激活：选择「到期日期 + 到期时刻」（北京时间），工具自动换算为有效小时数。
- ♾️ 永久激活：直接点「生成永久激活码」按钮，无需选择日期（内部使用远超阈值的大时长）。

**有效期规则**
- 起算时间固定为 **2026-09-01 00:00（北京时间）**，到期 = 起算 + 有效小时数。
- 机器码匹配且有效时长 **>= 0xFFFFFFFF（魔法值，≈49万年）** → 主程序视为**永久激活**，不再判断时间，可离线运行；正常到期日期远达不到该值，故限时码不会被误判。
- 限时激活码：主程序联网获取 **NTP 时间**并转北京时间判断是否过期（NTP 不可用时回退本机系统时间）。

**部署到 Streamlit Cloud**
1. 将本文件（可重命名为 `app.py`）与**精简后的** `requirements.txt`（只需 `streamlit`）推送到 **私有** GitHub 仓库；
2. 在 Streamlit Cloud 新建 App 并选择该仓库与文件；
3. 在 App → Settings → Secrets 配置访问口令（**务必设置**，否则页面回退到内置默认口令，等于公开）：
   `ACCESS_PASSWORD = "你的强口令"`
4. 部署后得到公开 URL，任何人访问都会先被口令门拦截，只有持口令者能进入。

**安全提示**
- **访问口令**（`ACCESS_PASSWORD`，存于云端 Secrets）决定「谁能打开本页」；**共享密钥** `ACTIVATION_SECRET`（内置于代码）决定「激活码如何签名」。两者层面不同，都要保护好。
- 共享密钥 `ACTIVATION_SECRET` 同时内置于本工具与桌面程序，二者必须一致。
- 本方案为「本地计算」的轻量授权，适合小额一次性收费场景；若仓库公开，密钥即公开，
  任何持有密钥者都能生成有效激活码。如需更强防伪，请改用非对称签名方案。
- 如需更换密钥：同时修改本文件与 `lucky_make_main.py` 的 `ACTIVATION_SECRET`，并重新打包 exe。
"""
        )
