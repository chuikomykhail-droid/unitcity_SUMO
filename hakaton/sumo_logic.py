import random
import subprocess
import os
import traci 
import xml.etree.ElementTree as ET

LOCATION_TO_EDGE = {
    "entrance": "reg_to_entrance",       
    "registration": "entrance_to_reg",   
    "hall": "reg_to_hall",               
    "cafe": "hall_to_cafe",              
    "shelter": "reg_to_shelter"          
}
SUMO_DIR = "sumo"

def time_to_sec(t):
    """Конвертирует datetime.time в секунды от начала суток"""
    return t.hour * 3600 + t.minute * 60 + t.second

def _generate_xml_files(events, groups):
    if not events:
        return None, None
        

    base_time = time_to_sec(events[0]["start_time"]) 

    os.makedirs(SUMO_DIR, exist_ok=True)
    route_file = os.path.join(SUMO_DIR, "campus.rou.xml")
    config_file = os.path.join(SUMO_DIR, "campus.sumocfg")


    persons_data = [] 
    
    for g_name, count in groups.items():
        for i in range(count):
            depart_offset = random.randint(0, 180) 
            
            p_xml = []
            p_xml.append(f'  <person id="{g_name.replace(" ", "_")}_{i}" depart="{depart_offset}">\n')
            
            current_edge = "entrance_to_reg" 
            
            for k in range(len(events)):
                target_loc = events[k]["targets"].get(g_name, "entrance")
                target_edge = LOCATION_TO_EDGE[target_loc]
                
                if k == 0:
                    p_xml.append(f'    <personTrip from="{current_edge}" to="{target_edge}"/>\n')
                    current_edge = target_edge
                elif current_edge != target_edge:
                    p_xml.append(f'    <personTrip to="{target_edge}"/>\n')
                    current_edge = target_edge

                end_time_sec = time_to_sec(events[k]["end_time"]) - base_time
                p_xml.append(f'    <stop lane="{current_edge}_0" until="{end_time_sec}"/>\n')
            

            if current_edge != LOCATION_TO_EDGE["entrance"]:
                p_xml.append(f'    <personTrip to="{LOCATION_TO_EDGE["entrance"]}"/>\n')
                
            p_xml.append('  </person>\n')
            persons_data.append((depart_offset, "".join(p_xml)))

    persons_data.sort(key=lambda x: x[0])

    with open(route_file, "w", encoding="utf-8") as f:
        f.write('<routes>\n')
        for _, person_xml in persons_data:
            f.write(person_xml)
        f.write('</routes>\n')

    with open(config_file, "w", encoding="utf-8") as f:
        f.write('<configuration>\n')
        f.write('    <input>\n')
        f.write('        <net-file value="campus.net.xml"/>\n')
        f.write('        <route-files value="campus.rou.xml"/>\n')
        f.write('    </input>\n')
        f.write('    <processing>\n')
        f.write('        <time-to-teleport value="10"/>\n') 
        f.write('    </processing>\n')
        f.write('</configuration>\n')
        
    return route_file, config_file


def generate_and_run_sumo(events, groups):
    """
    Генерирует файлы и открывает окно SUMO-GUI.
    (Вызывается при нажатии основной красной кнопки в Streamlit)
    """
    route_file, config_file = _generate_xml_files(events, groups)
    if not config_file:
        return
    
    subprocess.Popen(["sumo-gui", "-c", config_file])


def run_headless_simulation(events, groups):
    route_file, config_file = _generate_xml_files(events, groups)
    if not config_file: return 0
        
    tripinfo_file = os.path.join(SUMO_DIR, "tripinfo.xml")
    

    cmd = [
        "sumo", 
        "-c", config_file, 
        "--no-warnings", 
        "--no-step-log",
        "--tripinfo-output", tripinfo_file, 
    ]
    
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        
        total_time_loss = 0.0
        
  
        if os.path.exists(tripinfo_file):
            tree = ET.parse(tripinfo_file)
            root = tree.getroot()
            
            for personinfo in root.findall("personinfo"):
                for walk in personinfo.findall("walk"):
                    total_time_loss += float(walk.get("timeLoss", 0.0))
                    
            return int(total_time_loss)
            
        return 9999999 

    except subprocess.TimeoutExpired:
        return 9999999 
    except Exception as e:
        print(f"Помилка читання tripinfo: {e}")
        return 9999999