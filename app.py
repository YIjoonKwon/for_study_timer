import streamlit as st, pandas as pd, time, datetime, secrets, string
from sqlalchemy import create_engine, text
from streamlit_autorefresh import st_autorefresh

# ---------- DB 준비 ----------
engine = create_engine("sqlite:///study.db", future=True)
with engine.begin() as conn:
    conn.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS subjects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE, color TEXT);
    CREATE TABLE IF NOT EXISTS sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER,
        started_at DATETIME, ended_at DATETIME);
    CREATE TABLE IF NOT EXISTS groups(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, code TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS group_members(
        group_id INTEGER, nickname TEXT);
    """)

# ---------- 유틸 ----------
def sql(q, **params):
    with engine.begin() as c:
        return pd.read_sql(text(q), c, params=params)

def execute(q, **params):
    with engine.begin() as c:
        c.execute(text(q), params)

def nice_time(sec:int)->str:
    return f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}"

# ---------- 세션 상태 ----------
if "running" not in st.session_state:
    st.session_state.update(running=False, start_ts=None,
                            session_id=None, subject_id=None)

# ---------- 페이지 선택 ----------
page = st.sidebar.selectbox("메뉴", ["타이머","통계","그룹"])

# ---------- 과목 CRUD ----------
st.sidebar.header("과목 관리")
sub_df = sql("SELECT * FROM subjects ORDER BY id")
new_sub = st.sidebar.text_input("새 과목 이름")
new_color = st.sidebar.color_picker("색상 선택","#3b82f6")
if st.sidebar.button("추가") and new_sub:
    try:
        execute("INSERT INTO subjects(name,color) VALUES(:n,:c)",
                n=new_sub,c=new_color)
        st.sidebar.success("추가되었습니다."); st.experimental_rerun()
    except Exception as e:
        st.sidebar.error("이미 존재하거나 오류")

# ---------- 타이머 ----------
if page=="타이머":
    st.title("⏱️ 열품타 Lite (Streamlit)")
    st_autorefresh(interval=1000, key="refresh")  # 1초마다 새로고침

    # 과목 선택
    if sub_df.empty:
        st.info("왼쪽에서 과목을 먼저 추가하세요.")
        st.stop()
    names = {r.id:r.name for r in sub_df.itertuples()}
    subject_id = st.selectbox("과목", names.keys(),
                              format_func=lambda x: names[x],
                              index=list(names.keys()).index(
                                  st.session_state.get("subject_id",list(names)[0]))
                              )

    # 스톱워치 표시
    if st.session_state.running:
        elapsed = int(time.time() - st.session_state.start_ts)
    else:
        elapsed = 0
    st.markdown(f"<h1 style='text-align:center;'>{nice_time(elapsed)}</h1>",
                unsafe_allow_html=True)

    col1,col2 = st.columns(2)
    if not st.session_state.running:
        if col1.button("▶️ START", use_container_width=True):
            ts = int(time.time())
            execute("""INSERT INTO sessions(subject_id,started_at)
                       VALUES(:sid,datetime('now','localtime'))""",
                       sid=subject_id)
            session_id = sql("SELECT last_insert_rowid() as id").id.iloc[0]
            st.session_state.update(running=True,start_ts=ts,
                                    session_id=session_id,subject_id=subject_id)
            st.rerun()
    else:
        if col2.button("⏹ STOP", use_container_width=True):
            execute("""UPDATE sessions SET ended_at=datetime('now','localtime')
                       WHERE id=:id""", id=st.session_state.session_id)
            st.session_state.running=False
            st.session_state.start_ts=None
            st.experimental_rerun()

    # 오늘 기록
    today = sql("""SELECT s.id,sub.name,
                      (strftime('%s',COALESCE(s.ended_at,datetime('now','localtime')))
                       - strftime('%s',s.started_at)) AS sec
                   FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                   WHERE date(s.started_at,'localtime')=date('now','localtime')""")
    if not today.empty:
        st.subheader("오늘 누적")
        st.dataframe(today.groupby("name").sec.sum()
                     .apply(nice_time).reset_index()
                     .rename(columns={"sec":"time"}))

# ---------- 통계 ----------
elif page=="통계":
    st.title("📊 통계 / 달력")
    df = sql("""SELECT sub.name,color,
                   date(started_at,'localtime') as d,
                   (strftime('%s',COALESCE(ended_at,started_at))
                    - strftime('%s',started_at)) as sec
                FROM sessions JOIN subjects sub ON sub.id=subject_id""")
    if df.empty:
        st.info("아직 기록이 없습니다."); st.stop()

    # 주간 막대
    last7 = df[df.d >= (datetime.date.today()-datetime.timedelta(days=6)).isoformat()]
    st.subheader("최근 7일 합계")
    bar = last7.groupby("d").sec.sum().reset_index()
    st.bar_chart(bar, x="d", y="sec", height=200)

    # 과목 비율
    st.subheader("과목별 비율")
    pie = df.groupby("name").sec.sum().reset_index()
    st.altair_chart(
        (alt:=__import__("altair")).Chart(pie).mark_arc().encode(
            theta="sec", color="name", tooltip=["name","sec"]
        ), use_container_width=True)

    # 달력 heat-map
    st.subheader("달력")
    heat = df.groupby("d").sec.sum().reset_index()
    heat["dow"] = pd.to_datetime(heat.d).dt.dayofweek
    heat["week"] = pd.to_datetime(heat.d).dt.isocalendar().week
    base = alt.Chart(heat)
    st.altair_chart(
        base.mark_rect().encode(
            x="week:O", y="dow:O",
            color=alt.Color("sec:Q", scale=alt.Scale(scheme="greens")),
            tooltip=["d","sec"]
        ).properties(height=160), use_container_width=True)

# ---------- 그룹 ----------
else:
    st.title("👥 그룹")
    nickname = st.text_input("내 닉네임", value=st.session_state.get("nick",""))
    if nickname: st.session_state.nick=nickname
    mode = st.radio("옵션",["새 그룹 만들기","초대 코드로 가입"])
    if mode=="새 그룹 만들기":
        gname = st.text_input("그룹 이름")
        if st.button("생성") and gname:
            code=''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
            execute("INSERT INTO groups(name,code) VALUES(:n,:c)", n=gname,c=code)
            gid = sql("SELECT id FROM groups WHERE code=:c", c=code).id.iloc[0]
            execute("INSERT INTO group_members VALUES(:g,:n)", g=gid,n=nickname)
            st.success(f"생성 완료! 초대 코드: {code}")
    else:
        icode = st.text_input("초대 코드")
        if st.button("가입") and icode:
            g = sql("SELECT id FROM groups WHERE code=:c", c=icode)
            if g.empty:
                st.error("코드가 없습니다")
            else:
                execute("INSERT OR IGNORE INTO group_members VALUES(:g,:n)",
                        g=g.id.iloc[0], n=nickname)
                st.success("가입 완료!")

    # 내 그룹 목록
    if nickname:
        groups = sql("""SELECT g.name, g.code FROM groups g
                        JOIN group_members m ON m.group_id=g.id
                        WHERE m.nickname=:n""", n=nickname)
        if not groups.empty:
            st.subheader("내 그룹")
            st.table(groups)

