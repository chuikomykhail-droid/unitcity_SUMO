import streamlit as st
import datetime
import time
import uuid
import json
import re
import copy
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

from sumo_logic import generate_and_run_sumo, run_headless_simulation

# --- ІНІЦІАЛІЗАЦІЯ СТАНУ ---
if "original_backup" not in st.session_state:
    st.session_state.original_backup = None

if "ai_results" not in st.session_state:
    st.session_state.ai_results = None

# Тригер для модального вікна порівняння
if "just_optimized" not in st.session_state:
    st.session_state.just_optimized = False

if "groups" not in st.session_state:
    st.session_state.groups = {"Всі учасники": 500}

if "events" not in st.session_state:
    st.session_state.events = [{
        "id": str(uuid.uuid4()),
        "start_time": datetime.time(9, 30), 
        "end_time": datetime.time(10, 0),
        "name": "Початок реєстрації", 
        "targets": {"Всі учасники": "registration"}
    }]

# --- ФУНКЦІЇ МОДАЛЬНИХ ВІКОН ТА ФОРМАТУВАННЯ ---
def generate_schedule_markdown(events_list):
    if not events_list:
        return "Порожньо"
    md = ""
    for ev in sorted(events_list, key=lambda x: x["start_time"]):
        t_start = ev["start_time"].strftime("%H:%M")
        t_end = ev["end_time"].strftime("%H:%M")
        loc_str = ", ".join(set(ev["targets"].values()))
        icon = "" if "ТРИВОГА" in ev["name"].upper() else "🔹"
        md += f"{icon} **{t_start} - {t_end}** | {ev['name']} _({loc_str})_\n\n"
    return md

@st.dialog("⚖️ Порівняння розкладів: До та Після AI", width="large")
def show_comparison_modal():
    st.write("Ось як AI оптимізував ваші логістичні потоки та усунув затори:")
    col_before, col_after = st.columns(2)
    
    with col_before:
        st.error(" До оптимізації (Ваш варіант)")
        if st.session_state.original_backup:
            st.markdown(generate_schedule_markdown(st.session_state.original_backup["events"]))
        else:
            st.markdown("Немає збереженого бекапу")
            
    with col_after:
        st.success(" Після AI-каруселі")
        st.markdown(generate_schedule_markdown(st.session_state.events))
        
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Продовжити до симуляції", type="primary", use_container_width=True):
        st.session_state.just_optimized = False
        st.rerun()

# --- НАСТРОЙКА GEMINI API ---
API_KEY = "AQ.Ab8RN6JxwVy0kGdL-ZLGSQfybqXetFhDn-kMrUNX23u1wLX9_w"
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')

st.set_page_config(page_title="UNIT.City Event Sandbox", layout="wide")

# CSS для збільшення кнопок
st.markdown("""
<style>
div[data-testid="stButton"] button p {
    font-size: 20px !important;
    font-weight: 600 !important;
}
div[data-testid="stButton"] button {
    height: auto !important;
    padding-top: 12px !important;
    padding-bottom: 12px !important;
}
</style>
""", unsafe_allow_html=True)

LOCATIONS = ["entrance", "registration", "hall", "cafe", "shelter"]

# --- ФУНКЦІЇ ОБРОБНИКИ ДАНИХ ---
def add_group(name, count):
    if name and name not in st.session_state.groups:
        st.session_state.groups[name] = count
        for event in st.session_state.events:
            event["targets"][name] = "entrance"

def remove_group(name):
    if name in st.session_state.groups:
        del st.session_state.groups[name]
    for event in st.session_state.events:
        if name in event["targets"]:
            del event["targets"][name]

def add_event(start_time, end_time, name):
    new_targets = {g_name: "entrance" for g_name in st.session_state.groups.keys()}
    st.session_state.events.append({
        "id": str(uuid.uuid4()),
        "start_time": start_time, 
        "end_time": end_time, 
        "name": name, 
        "targets": new_targets
    })
    sort_events()

def remove_event(event_id):
    st.session_state.events = [e for e in st.session_state.events if e["id"] != event_id]

def sort_events():
    st.session_state.events = sorted(st.session_state.events, key=lambda x: x["start_time"])

def insert_air_raid_alert(alert_start, alert_end, shelter_loc):
    dummy_date = datetime.date(2000, 1, 1)
    dt_alert_start = datetime.datetime.combine(dummy_date, alert_start)
    dt_alert_end = datetime.datetime.combine(dummy_date, alert_end)

    if dt_alert_start >= dt_alert_end:
        st.error("Відбій має бути пізніше за початок тривоги!")
        return

    alert_duration = dt_alert_end - dt_alert_start
    new_events = []
    alert_added = False

    sorted_events = sorted(st.session_state.events, key=lambda x: x["start_time"])

    for ev in sorted_events:
        dt_start = datetime.datetime.combine(dummy_date, ev["start_time"])
        dt_end = datetime.datetime.combine(dummy_date, ev["end_time"])

        if dt_end <= dt_alert_start:
            new_events.append(ev)
            continue

        if dt_start >= dt_alert_start:
            if not alert_added:
                new_events.append({
                    "id": str(uuid.uuid4()),
                    "start_time": alert_start,
                    "end_time": alert_end,
                    "name": " ПОВІТРЯНА ТРИВОГА",
                    "targets": {g: shelter_loc for g in st.session_state.groups.keys()}
                })
                alert_added = True

            ev["start_time"] = (dt_start + alert_duration).time()
            ev["end_time"] = (dt_end + alert_duration).time()
            new_events.append(ev)
            continue

        ev_part1 = copy.deepcopy(ev)
        ev_part1["id"] = str(uuid.uuid4())
        ev_part1["end_time"] = alert_start
        new_events.append(ev_part1)

        if not alert_added:
            new_events.append({
                "id": str(uuid.uuid4()),
                "start_time": alert_start,
                "end_time": alert_end,
                "name": " ПОВІТРЯНА ТРИВОГА",
                "targets": {g: shelter_loc for g in st.session_state.groups.keys()}
            })
            alert_added = True

        ev_part2 = copy.deepcopy(ev)
        ev_part2["id"] = str(uuid.uuid4())
        ev_part2["name"] = f"{ev['name']} (продовження)"
        
        remaining_duration = dt_end - dt_alert_start
        ev_part2["start_time"] = alert_end
        ev_part2["end_time"] = (dt_alert_end + remaining_duration).time()
        new_events.append(ev_part2)

    if not alert_added:
        new_events.append({
            "id": str(uuid.uuid4()),
            "start_time": alert_start,
            "end_time": alert_end,
            "name": " ПОВІТРЯНА ТРИВОГА",
            "targets": {g: shelter_loc for g in st.session_state.groups.keys()}
        })

    st.session_state.events = new_events

# --- ІНТЕРФЕЙС ---
st.title("UNIT.City Predictive Campus")
st.markdown("Конструктор логістики натовпу з інтеграцією Agentic AI")

col_settings, col_dashboard = st.columns([1.5, 1])

with col_settings:
    # 1. ФОРМУВАННЯ ГРУП
    st.header(" 1. Формування груп")
    for g_name in list(st.session_state.groups.keys()):
        col_name, col_count, col_del = st.columns([3, 2, 1])
        with col_name:
            st.markdown(f"<div style='margin-top:8px;'><b>{g_name}</b></div>", unsafe_allow_html=True)
        with col_count:
            st.session_state.groups[g_name] = st.number_input("Кількість", value=st.session_state.groups[g_name], min_value=1, key=f"count_{g_name}", label_visibility="collapsed")
        with col_del:
            if len(st.session_state.groups) > 1:
                if st.button("🗑️", key=f"del_g_{g_name}", help="Видалити групу"):
                    remove_group(g_name)
                    st.rerun()
            else:
                st.button("🔒", key=f"lock_g_{g_name}", disabled=True)
        
    with st.expander("➕ Додати нову групу"):
        col1, col2 = st.columns([3, 2])
        with col1: new_g_name = st.text_input("Назва групи", placeholder="Наприклад, VIP")
        with col2: new_g_count = st.number_input("Кількість людей", min_value=1, value=50, step=10)
        if st.button("Створити групу", use_container_width=True):
            add_group(new_g_name, new_g_count)
            st.rerun()

    st.markdown("---")
    
    # 2. РОЗКЛАД ТА МАРШРУТИЗАЦІЯ
    st.header(" 2. Розклад та маршрутизація")
    if st.button("Відсортувати події за часом", use_container_width=True):
        sort_events()
        st.rerun()
        
    st.markdown("<br>", unsafe_allow_html=True)

    for i, event in enumerate(st.session_state.events):
        ev_id = event["id"]
        with st.container(border=True):
            col_name, col_start, col_end, col_del = st.columns([3, 2, 2, 1])
            with col_name:
                event["name"] = st.text_input("Подія", value=event["name"], key=f"name_{ev_id}", label_visibility="collapsed")
            with col_start:
                event["start_time"] = st.time_input("Початок", value=event["start_time"], key=f"start_{ev_id}", label_visibility="collapsed")
            with col_end:
                event["end_time"] = st.time_input("Кінець", value=event["end_time"], key=f"end_{ev_id}", label_visibility="collapsed")
            with col_del:
                if len(st.session_state.events) > 1:
                    if st.button("🗑️", key=f"del_e_{ev_id}", help="Видалити подію"):
                        remove_event(ev_id)
                        st.rerun()
                else:
                    st.button("🔒", key=f"lock_e_{ev_id}", disabled=True)

            if st.session_state.groups:
                group_cols = st.columns(len(st.session_state.groups))
                for j, g_name in enumerate(st.session_state.groups.keys()):
                    event["targets"][g_name] = group_cols[j].selectbox(
                        f"Маршрут для {g_name}:", 
                        LOCATIONS, 
                        index=LOCATIONS.index(event["targets"].get(g_name, "entrance")),
                        key=f"loc_{ev_id}_{g_name}"
                    )

    with st.expander("➕ Додати нову подію"):
        col1, col2 = st.columns(2)
        with col1: new_start = st.time_input("Новий початок", datetime.time(12, 0))
        with col2: new_end = st.time_input("Новий кінець", datetime.time(13, 0))
        new_name = st.text_input("Назва", placeholder="Обід")
        
        if st.button("Додати подію", use_container_width=True):
            add_event(new_start, new_end, new_name)
            st.rerun()

    st.markdown("---")
    
    # 3. ФОРС-МАЖОРИ
    st.header(" 3. Форс-мажори")
    with st.expander("Додати Повітряну Тривогу"):
        st.info("Автоматично перерве події, відправить усіх в укриття, а після відбою — зсуне розклад.")
        col1, col2 = st.columns(2)
        with col1: a_start = st.time_input("Початок тривоги", datetime.time(11, 0))
        with col2: a_end = st.time_input("Відбій тривоги", datetime.time(11, 45))
        
        default_index = LOCATIONS.index("shelter") if "shelter" in LOCATIONS else 0
        a_loc = st.selectbox("Локація укриття", LOCATIONS, index=default_index)

        if st.button(" Застосувати тривогу", type="primary", use_container_width=True):
            if any("ТРИВОГА" in ev["name"].upper() for ev in st.session_state.events):
                st.warning(" Спочатку скасуйте поточну тривогу.")
                st.stop()
            
            st.session_state.original_backup = {
                "groups": copy.deepcopy(st.session_state.groups),
                "events": copy.deepcopy(st.session_state.events)
            }
            insert_air_raid_alert(a_start, a_end, a_loc)
            st.rerun()

with col_dashboard:
    # 4. СИМУЛЯЦІЯ ТА AI
    st.header(" 4. Симуляція")
    
    st.subheader("Зведений план")
    sorted_events = sorted(st.session_state.events, key=lambda x: x["start_time"])
    
    summary_data = []
    for e in sorted_events:
        row = {
            "Час": f"{e['start_time'].strftime('%H:%M')}-{e['end_time'].strftime('%H:%M')}", 
            "Подія": e["name"]
        }
        row.update(e["targets"])
        summary_data.append(row)
        
    st.dataframe(summary_data, hide_index=True, use_container_width=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    visualize = st.checkbox("Візуалізувати (SUMO-GUI)", value=True)
    
    if st.button("ЗГЕНЕРУВАТИ ТА ЗАПУСТИТИ", use_container_width=True, type="primary"):
        if visualize:
            # Спочатку відкриваємо візуалізацію
            with st.spinner("Симуляція йде у SUMO-GUI... (закрийте вікно програми після перегляду)"):
                generate_and_run_sumo(sorted_events, st.session_state.groups)
            
            # Після закриття вікна SUMO виводимо результат
            with st.spinner("Підбиваємо підсумки..."):
                score = run_headless_simulation(sorted_events, st.session_state.groups)
                st.success("Симуляція завершена!")
                st.metric(label="Штрафні бали (секунди в заторах)", value=score)
        else:
            # Якщо без візуалізації - просто миттєво рахуємо
            with st.spinner("Прорахунок у фоні (Headless)..."):
                score = run_headless_simulation(sorted_events, st.session_state.groups)
                st.metric(label="Штрафні бали (секунди в заторах)", value=score)
    st.markdown("---")

    # АГЕНТСЬКИЙ AI
    if st.button("✨ Допомога AI (Згенерувати стратегії)", type="primary", use_container_width=True):
        if any("ТРИВОГА" in ev["name"].upper() for ev in st.session_state.events):
            st.warning("Оптимізація неможлива: у розкладі присутній форс-мажор. Спочатку скасуйте тривогу.")
            st.stop()
            
        if API_KEY == "ВСТАВЬТЕ_ВАШ_КЛЮЧ_СЮДА":
            st.error("Вставте API-ключ Gemini у код!")
            st.stop()
            
        st.session_state.original_backup = {
            "groups": copy.deepcopy(st.session_state.groups),
            "events": copy.deepcopy(st.session_state.events)
        }
            
        with st.spinner("1/4: Заміряємо поточний розклад у SUMO..."):
            baseline_score = run_headless_simulation(sorted_events, st.session_state.groups)
            
        with st.spinner("2/4: AI придумує альтернативні логістичні рішення (це може зайняти час)..."):
            schedule_context = str([{
                "start_time": e['start_time'].strftime('%H:%M'), 
                "end_time": e['end_time'].strftime('%H:%M'), 
                "name": e['name'], 
                "targets": e['targets']
            } for e in sorted_events])
            
            prompt = f"""
            Ти логіст івенту. Поточні групи: {st.session_state.groups}. Поточний розклад: {schedule_context}.
            Згенеруй 2 альтернативні стратегії оптимізації. ТИ МАЄШ ПРАВО розбивати великі групи на менші.
            
            🚨 СУВОРІ ПРАВИЛА ОПТИМІЗАЦІЇ (КРИТИЧНО):
            1. ЛІНІЙНІСТЬ ЧАСУ: Хронологія подій має бути суворо послідовною. Час різних подій у масиві 'events' НЕ МОЖЕ перетинатися або накладатися! 
            2. ЗБЕРЕЖЕННЯ СТРУКТУРИ: Всі події з оригіналу мають бути в розкладі.
            3. ЖОРСТКІ ЧАСОВІ МЕЖІ: Загальна тривалість івенту НЕ МОЖЕ збільшуватися. Якщо в оригіналі обід тривав 50 хвилин, то при розбитті на дві групи ти маєш поділити цей час!
            4. МАТЕМАТИКА ГРУП: Загальна кількість людей має залишатися незмінною.
            5. ДОЗВОЛЕНІ ДІЇ: Використовуй "карусель" (staggering).
            6. ФІЗИКА БУДІВЛІ ТА БУФЕРИ: Щоб уникнути зіткнення, одна група ПОВИННА чекати на своїй старій локації 5 хвилин, поки інша переходить. 
            7. ЛОКАЦІЇ (ВАЖЛИВО): Для маршрутів (targets) використовуй ТІЛЬКИ: "registration", "hall", "cafe". КАТЕГОРИЧНО ЗАБОРОНЕНО використовувати "entrance" або "shelter" всередині розкладу.
            
            Поверни ТІЛЬКИ масив JSON...
            """
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = model.generate_content(prompt)
                    match = re.search(r'\[.*\]', response.text, re.DOTALL)
                    if not match:
                        st.error("AI повернув невірний формат. Спробуйте ще раз.")
                        st.stop()
                    ai_strategies = json.loads(match.group(0))
                    break 
                    
                except ResourceExhausted:
                    if attempt < max_retries - 1:
                        st.warning(f"Перевищено безкоштовний ліміт запитів до API. Очікування 20 секунд...")
                        time.sleep(20)
                    else:
                        st.error("Ліміт Google API вичерпано.")
                        st.stop()
                        
                except Exception as e:
                    st.error(f"Помилка генерації гіпотез: {e}")
                    st.stop()

        with st.spinner("3/4: Симулюємо ідеї AI у движку SUMO..."):
            results_text = f"Оригінальний розклад отримав {baseline_score} штрафних балів.\n\n"
            
            for strategy in ai_strategies:
                for ev in strategy["events"]:
                    ev["start_time"] = datetime.datetime.strptime(ev["start_time"], "%H:%M").time()
                    ev["end_time"] = datetime.datetime.strptime(ev["end_time"], "%H:%M").time()
                
                ai_groups = strategy.get("groups", st.session_state.groups)
                score = run_headless_simulation(strategy["events"], ai_groups)
                strategy["score"] = score
                results_text += f"Стратегія '{strategy['strategy_name']}' отримала {score} штрафних балів.\n"
                
        with st.spinner("4/4: AI формує фінальний аналітичний звіт..."):
            prompt_2 = f"""
            Ти проаналізував симуляції натовпу. Результати:
            {results_text}
            Напиши короткий бізнес-звіт (до 4 абзаців) українською мовою. Поясни, яка стратегія перемогла і чому.
            """
            try:
                time.sleep(2) 
                final_report = model.generate_content(prompt_2).text
            except ResourceExhausted:
                final_report = "AI перевищив ліміт API. Оберіть стратегію самостійно!"
            except Exception as e:
                final_report = f"Помилка AI: {e}"
            
        st.session_state.ai_results = {
            "baseline": baseline_score,
            "strategies": ai_strategies,
            "report": final_report
        }
        st.rerun()

    if st.session_state.original_backup:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Скасувати зміни AI та повернути мій розклад", use_container_width=True):
            st.session_state.groups = copy.deepcopy(st.session_state.original_backup["groups"])
            st.session_state.events = copy.deepcopy(st.session_state.original_backup["events"])
            st.session_state.original_backup = None
            st.session_state.ai_results = None
            st.rerun()
    
    if st.session_state.ai_results:
        with st.container(border=True):
            st.markdown("### Аналітичний звіт AI")
            st.markdown(st.session_state.ai_results["report"])
            st.divider()
            
            cols = st.columns(len(st.session_state.ai_results["strategies"]) + 1)
            cols[0].metric("Ваш розклад", value=f"{st.session_state.ai_results['baseline']}")
            
            for idx, strategy in enumerate(st.session_state.ai_results["strategies"]):
                with cols[idx + 1]:
                    st.metric(f"AI: {strategy['strategy_name']}", value=f"{strategy['score']}")
                    
                    if st.button("Застосувати", key=f"apply_ai_{idx}", type="primary", use_container_width=True):
                        st.session_state.groups = strategy.get("groups", st.session_state.groups)
                        
                        new_events = []
                        for ev in strategy["events"]:
                            ev["id"] = str(uuid.uuid4())
                            new_events.append(ev)
                        st.session_state.events = new_events
                        
                        st.session_state.ai_results = None
                        st.session_state.just_optimized = True # ТРИГЕР ВІКНА "ДО/ПІСЛЯ"
                        st.rerun()

# --- ВИКЛИК МОДАЛЬНИХ ВІКОН В КІНЦІ СКРИПТА ---
if st.session_state.get("just_optimized", False):
    show_comparison_modal()