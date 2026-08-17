from pathlib import Path

import pandas as pd


root = Path(__file__).resolve().parents[1]
output = root / "data" / "planning.xlsx"
output.parent.mkdir(parents=True, exist_ok=True)

workers = pd.DataFrame([
    {"Worker": "Aisha", "Skill": "welding", "Skills": "welding, inspection", "Certifications": "hot-work", "Available": True, "Calendar": "Mon: 08:00-17:00\nTue: 08:00-17:00", "Location": "workshop", "Cost_Per_Hour": 35, "Current_Workload_Hours": 0},
    {"Worker": "Ben", "Skill": "welding", "Skills": "welding", "Certifications": "hot-work", "Available": True, "Calendar": "Shift: 20:00-08:00", "Location": "workshop", "Cost_Per_Hour": 30, "Current_Workload_Hours": 2},
    {"Worker": "Chen", "Skill": "machining", "Skills": "machining, inspection", "Certifications": "cnc", "Available": True, "Calendar": "Mon: 08:00-17:00\nTue: 08:00-17:00", "Location": "machine-shop", "Cost_Per_Hour": 40, "Current_Workload_Hours": 0},
])
machines = pd.DataFrame([
    {"Machine": "WELD-01", "Type": "welder", "Capabilities": "welder, frame-welding", "Available": True, "Calendar": "Mon: 24h\nTue: maintenance 10:00-14:00", "Location": "workshop", "Operating_Cost_Per_Hour": 12},
    {"Machine": "CNC-01", "Type": "cnc", "Capabilities": "cnc, plate-cutting", "Available": True, "Calendar": "Mon: 24h\nTue: 24h", "Location": "machine-shop", "Operating_Cost_Per_Hour": 25},
    {"Machine": "CNC-02", "Type": "cnc", "Capabilities": "cnc, plate-cutting", "Available": True, "Calendar": "Mon: 24h\nTue: maintenance 10:00-14:00", "Location": "machine-shop", "Operating_Cost_Per_Hour": 22},
])
vehicles = pd.DataFrame([
    {"Vehicle": "FORK-01", "Type": "forklift", "Capabilities": "forklift, indoor transport", "Available": True, "Calendar": "Mon: 08:00-18:00\nTue: 08:00-18:00", "Location": "workshop", "Operating_Cost_Per_Hour": 8},
])
tasks = pd.DataFrame([
    {"Task": "Cut plate", "Duration_Hours": 3, "Setup_Hours": 0.5, "Travel_Hours": 0.25, "Priority": "high", "Deadline_Days": 1, "Location": "machine-shop", "Required_Skill": "machining", "Required_Skills": "machining", "Required_Certifications": "cnc", "Workers_Needed": 1, "Machine_Type": "cnc", "Machine_Requirements": "cnc, plate-cutting", "Predecessors": "", "Vehicle_Type": "", "Setup_Requirements": "plate fixture"},
    {"Task": "Weld frame", "Duration_Hours": 4, "Setup_Hours": 0.5, "Travel_Hours": 0.25, "Priority": "critical", "Deadline_Days": 1, "Location": "workshop", "Required_Skill": "welding", "Required_Skills": "welding", "Required_Certifications": "hot-work", "Workers_Needed": 2, "Machine_Type": "welder", "Machine_Requirements": "welder, frame-welding", "Predecessors": "Cut plate", "Vehicle_Type": "", "Setup_Requirements": "welding screen"},
    {"Task": "Move frame", "Duration_Hours": 1, "Setup_Hours": 0.25, "Travel_Hours": 0.5, "Priority": "medium", "Deadline_Days": 2, "Location": "dispatch", "Required_Skill": "welding", "Required_Skills": "welding", "Required_Certifications": "hot-work", "Workers_Needed": 1, "Machine_Type": "welder", "Machine_Requirements": "welder", "Predecessors": "Weld frame", "Vehicle_Type": "forklift", "Vehicle_Requirements": "forklift, indoor transport", "Setup_Requirements": "load securement"},
])
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    workers.to_excel(writer, sheet_name="Workers", index=False)
    tasks.to_excel(writer, sheet_name="Tasks", index=False)
    machines.to_excel(writer, sheet_name="Machines", index=False)
    vehicles.to_excel(writer, sheet_name="Vehicles", index=False)
print(f"Created {output}")
