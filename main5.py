import os
import sqlite3
import math
import json
import time
import random
from datetime import datetime, timedelta
from hashlib import sha256
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from functools import wraps

from flask import Flask, request, session, redirect, url_for, render_template_string, jsonify, abort
from jinja2 import DictLoader

# Twilio integration - handle optional dependency
try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    print("Twilio not installed. SMS/WhatsApp alerts will be disabled.")

# ---------------- Flask app ----------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey_change_me_in_production")
DB = "disaster_ops.db"

# ---------------- Twilio Configuration ----------------
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')  # Twilio sandbox number
TWILIO_SMS_FROM = os.environ.get('TWILIO_SMS_FROM', '')  # Regular SMS number

# Initialize Twilio client only if credentials are provided
twilio_client = None
if TWILIO_AVAILABLE and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        print("Twilio client initialized successfully.")
    except Exception as e:
        print(f"Twilio initialization error: {e}")
        twilio_client = None
else:
    if TWILIO_AVAILABLE:
        print("Twilio credentials not found in environment variables.")
    print("SMS/WhatsApp alerts will be disabled.")

# ---------------- HTML Templates ----------------
html_base = {
    "layout": """
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width,initial-scale=1"/>
    <title>{{ title }}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
    <style>
    :root{--bg:#0b0e16;--panel:#121726;--muted:#9aa4bf;--accent:#00e0a4;--accent2:#ff4d8d;--text:#e6ecff;--danger:#ff3b30;--ok:#4cd964}
    *{box-sizing:border-box}
    body{margin:0;background:radial-gradient(80vw 80vh at 0% 0%,#121726,#0b0e16);color:var(--text);font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
    .header{display:flex;gap:.75rem;align-items:center;justify-content:space-between;padding:1rem 1.25rem;border-bottom:1px solid #1b2237;background:linear-gradient(180deg,#121726 0%,#0f1424 100%);position:sticky;top:0;z-index:50}
    .brand{display:flex;gap:.6rem;align-items:center;font-weight:800;letter-spacing:.2px}
    .logo{width:36px;height:36px;border-radius:12px;background:conic-gradient(from 0deg at 50% 50%,var(--accent),#09f,var(--accent2),var(--accent));box-shadow:0 0 30px rgba(0,224,164,.25)}
    .badge{padding:.25rem .5rem;border:1px solid #213052;border-radius:999px;color:var(--muted);font-size:.75rem}
    .nav{display:flex;gap:.5rem;align-items:center}
    .nav a{color:var(--muted);text-decoration:none;padding:.5rem .75rem;border-radius:.7rem;transition:.2s}
    .nav a.active,.nav a:hover{background:#151c33;color:#fff}
    .cta{background:linear-gradient(90deg,var(--accent),#09f);color:#001a12;border:none;padding:.55rem .9rem;border-radius:.8rem;font-weight:700;cursor:pointer}
    .container{padding:1rem;max-width:1200px;margin:0 auto}
    .grid{display:grid;gap:1rem}
    .cards{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
    .card{background:linear-gradient(180deg,#0e1426,#0b1120);border:1px solid #1c2745;border-radius:1rem;padding:1rem;box-shadow:0 10px 30px rgba(0,0,0,.25)}
    .kpi{font-size:1.8rem;font-weight:800}
    .kpi-sub{font-size:.85rem;color:var(--muted)}
    .form{display:grid;gap:.6rem}
    .input,select,textarea{background:#0b1222;border:1px solid #1d2849;color:#fff;padding:.65rem .8rem;border-radius:.6rem;width:100%}
    .button{background:linear-gradient(90deg,var(--accent),#09f);border:none;padding:.7rem 1rem;border-radius:.8rem;color:#001a12;font-weight:800;cursor:pointer}
    .button.alt{background:#151c33;color:#dbe7ff;border:1px solid #223053}
    .status{padding:.25rem .5rem;border-radius:.5rem;font-size:.75rem}
    .status.open{background:#131f3e;color:#fff;border:1px solid #27406b}
    .status.assigned{background:#0f2b22;color:#9affe2;border:1px solid #1a5847}
    .status.closed{background:#2a1420;color:#ffc7dc;border:1px solid #5a2a43}
    .status.in_progress{background:#2a2a14;color:#ffffc7;border:1px solid #5a5a2a}
    .table{width:100%;border-collapse:collapse}
    .table th,.table td{padding:.6rem;border-bottom:1px solid #1d2849;text-align:left}
    .hero{display:grid;grid-template-columns:1.1fr .9fr;gap:1.2rem;align-items:center}
    .hero h1{font-size:2rem;margin:.3rem 0}
    .hero p{color:var(--muted)}
    .map{height:480px;border-radius:1rem;overflow:hidden;border:1px solid #1b2646}
    .tag{display:inline-flex;gap:.4rem;align-items:center;padding:.25rem .45rem;border:1px dashed #27406b;border-radius:.5rem;color:#9bd1ff;font-size:.8rem}
    .footer{color:var(--muted);text-align:center;padding:2rem 1rem}
    @media(max-width:900px){.hero{grid-template-columns:1fr}.map{height:380px}}
    .legend{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
    .legend .chip{width:10px;height:10px;border-radius:999px;display:inline-block}
    .legend .sev-extreme{background:#ff3b30}.legend .sev-severe{background:#ff9f0a}.legend .sev-moderate{background:#ffd60a}.legend .sev-minor{background:#4cd964}
    .coordinates-display{position:absolute;bottom:10px;right:10px;background:rgba(0,0,0,0.7);padding:5px 10px;border-radius:4px;z-index:1000;font-size:12px}
    .role-badge{background:var(--accent);color:#001a12;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600}
    .alert-success{background:#0f2b22;color:#9affe2;padding:10px;border-radius:8px;margin:10px 0}
    .alert-error{background:#2a1420;color:#ffc7dc;padding:10px;border-radius:8px;margin:10px 0}
    .alert-info{background:#1a2236;color:#9aa4bf;padding:10px;border-radius:8px;margin:10px 0}
    .alert-warning{background:#2a2a14;color:#fff3c7;padding:10px;border-radius:8px;margin:10px 0}
    </style>
    </head>
    <body>
    <div class=header>
    <div class=brand><div class=logo></div>DDR<span class=badge>Disaster Debris Response</span></div>
    <div class=nav>
    {% if session.user.role in ['admin', 'reporter', 'coordinator', 'viewer'] %}
    <a href="{{ url_for('dashboard') }}" class="{% if active=='dashboard' %}active{% endif %}">Dashboard</a>
    {% endif %}
    {% if session.user.role in ['admin', 'reporter', 'viewer'] %}
    <a href="{{ url_for('predict') }}" class="{% if active=='predict' %}active{% endif %}">Risk Map</a>
    {% endif %}
    {% if session.user.role in ['admin', 'reporter'] %}
    <a href="{{ url_for('report_incident') }}" class="{% if active=='report' %}active{% endif %}">Report</a>
    {% endif %}
    {% if session.user.role in ['admin', 'coordinator'] %}
    <a href="{{ url_for('assign_tasks') }}" class="{% if active=='assign' %}active{% endif %}">Assign</a>
    <a href="{{ url_for('resources') }}" class="{% if active=='resources' %}active{% endif %}">Resources</a>
    {% endif %}
    {% if session.user.role == 'volunteer' %}
    <a href="{{ url_for('volunteer_tasks') }}" class="{% if active=='tasks' %}active{% endif %}">My Tasks</a>
    {% endif %}
    {% if session.user.role in ['admin', 'coordinator'] %}
    <a href="{{ url_for('alerts') }}" class="{% if active=='alerts' %}active{% endif %}">Alerts</a>
    {% endif %}
    <span class="role-badge">{{ session.user.role }}</span>
    <a href="{{ url_for('logout') }}">Logout</a>
    </div>
    </div>
    <div class=container>
    {% if message_sent %}
        {% if message_sent[0] == 'success' %}
        <div class="alert-success">{{ message_sent[1] }}</div>
        {% elif message_sent[0] == 'error' %}
        <div class="alert-error">{{ message_sent[1] }}</div>
        {% elif message_sent[0] == 'info' %}
        <div class="alert-info">{{ message_sent[1] }}</div>
        {% elif message_sent[0] == 'warning' %}
        <div class="alert-warning">{{ message_sent[1] }}</div>
        {% endif %}
    {% endif %}
    {% block content %}{% endblock %}
    </div>
    <div class=footer>Built for rapid response and planning • {{ now }}</div>
    </body>
    </html>
    """,
    "login": """
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Login • DDR</title>
    <link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
    :root{--bg:#0b0e16;--panel:#121726;--muted:#9aa4bf;--accent:#00e0a4;--text:#e6ecff}
    *{box-sizing:border-box}
    body{margin:0;background:radial-gradient(80vw 80vh at 0% 0%,#121726,#0b0e16);color:var(--text);font-family:Inter,system-ui}
    .wrap{min-height:100vh;display:grid;place-items:center;padding:1.25rem}
    .card{width:100%;max-width:420px;background:linear-gradient(180deg,#0f1423,#0b1120);padding:1.2rem;border-radius:1.1rem;border:1px solid #1b2646;box-shadow:0 10px 40px rgba(0,0,0,.35)}
    .card h1{margin:.2rem 0 1rem 0}
    .input{width:100%;padding:.8rem;border-radius:.7rem;background:#0b1222;border:1px solid #1d2849;color:#fff;margin:.4rem 0}
    .button{width:100%;padding:.85rem;border:none;border-radius:.8rem;background:linear-gradient(90deg,var(--accent),#09f);color:#001a12;font-weight:800;cursor:pointer}
    .m{color:#ff96b0;font-size:.9rem}
    .small{color:#9aa4bf;text-align:center;margin-top:1rem}
    </style>
    </head>
    <body>
    <div class=wrap>
    <form method=post class=card>
    <h1>Sign in</h1>
    <input class=input name=username placeholder=Username required>
    <input class=input type=password name=password placeholder=Password required>
    <button class=button>Login</button>
    {% if message %}<div class=m>{{ message }}</div>{% endif %}
    <div class=small>Default: admin / admin123</div>
    <div class=small>Need an account? <a href="{{ url_for('register') }}">Register</a></div>
    </form>
    </div>
    </body>
    </html>
    """,
    "register": """
    {% extends 'layout' %}
    {% block content %}
    <div class=card style="max-width:500px;margin:2rem auto">
    <h1>Register New User</h1>
    <form method=post class=form>
    <input class=input name=username placeholder="Username" required>
    <input class=input type=password name=password placeholder="Password" required>
    <select class=input name=role required>
    <option value="">Select Role</option>
    <option value="admin">Admin</option>
    <option value="coordinator">Coordinator</option>
    <option value="reporter">Reporter</option>
    <option value="volunteer">Volunteer</option>
    <option value="viewer">Viewer</option>
    </select>
    <input class=input name=contact placeholder="Phone Number (for alerts)" type="tel">
    <button class=button>Register</button>
    </form>
    <div style="margin-top:1rem;text-align:center">
    <a href="{{ url_for('login') }}">Back to Login</a>
    </div>
    </div>
    {% endblock %}
    """,
    "dashboard": """
    {% extends 'layout' %}
    {% block content %}
    <div class=hero>
    <div>
    <h1>Operational Dashboard</h1>
    <p>Plan proactively with probabilistic debris risk, then coordinate incidents, volunteers, evacuations, and relief resources in one system.</p>
    <div class=grid cards>
    <div class=card><div class=kpi>{{ kpis.total_incidents }}</div><div class=kpi-sub>Incidents</div></div>
    <div class=card><div class=kpi>{{ kpis.open_incidents }}</div><div class=kpi-sub>Open</div></div>
    <div class=card><div class=kpi>{{ kpis.volunteers }}</div><div class=kpi-sub>Volunteers Available</div></div>
    <div class=card><div class=kpi>{{ kpis.resources }}</div><div class=kpi-sub>Resource Items</div></div>
    </div>
    </div>
    <div class=card>
    <div class="legend" style="margin-bottom:.5rem">
    <span>Live NDMA (SACHET) Alerts:</span>
    <span class="chip sev-extreme"></span><span>Extreme</span>
    <span class="chip sev-severe"></span><span>Severe</span>
    <span class="chip sev-moderate"></span><span>Moderate</span>
    <span class="chip sev-minor"></span><span>Minor</span>
    </div>
    <div id=map class=map></div>
    <div id="coordinates" class="coordinates-display">Lat: 0.0000, Lng: 0.0000</div>
    </div>
    </div>
    <div class=card>
    <h2>Recent Incidents</h2>
    <table class=table>
    <tr><th>ID</th><th>Type</th><th>Severity</th><th>Lat</th><th>Lng</th><th>Status</th><th>Reported</th></tr>
    {% for i in incidents %}
    <tr><td>{{ i['id'] }}</td><td>{{ i['type'] }}</td><td>{{ i['severity'] }}</td><td>{{ '%.4f'|format(i['lat']) }}</td><td>{{ '%.4f'|format(i['lng']) }}</td><td><span class="status {{ i['status'] }}">{{ i['status'] }}</span></td><td>{{ i['reported_at'] }}</td></tr>
    {% endfor %}
    </table>
    </div>
    <script>
    function colorBySeverity(s){
    s=(s||'').toLowerCase();
    if(s.includes('extreme')) return '#ff3b30';
    if(s.includes('severe')) return '#ff9f0a';
    if(s.includes('moderate')) return '#ffd60a';
    return '#4cd964';
    }

    var map=L.map('map').setView([23.5,80.0],5)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map)

    // Display coordinates on mouse move
    map.on('mousemove', function(e) {
        document.getElementById('coordinates').innerText = 'Lat: ' + e.latlng.lat.toFixed(4) + ', Lng: ' + e.latlng.lng.toFixed(4);
    });

    fetch('{{ url_for("api_incidents") }}').then(r=>r.json()).then(d=>{
    d.forEach(x=>{
        var m=L.circleMarker([x.lat,x.lng],{radius:6}).addTo(map);
        m.bindPopup('[#'+x.id+'] '+x.type+' • severity '+x.severity+' • '+x.status+'<br>Lat: '+x.lat.toFixed(4)+', Lng: '+x.lng.toFixed(4));
    })
    })

    fetch('{{ url_for("api_hotspots") }}').then(r=>r.json()).then(d=>{
    if(window.L.heatLayer){L.heatLayer(d.map(p=>[p.lat,p.lng,p.w]),{radius:25,blur:15}).addTo(map)}
    })

    fetch('{{ url_for("api_hospitals") }}').then(r=>r.json()).then(d=>{
    d.forEach(h=>{var m=L.marker([h.lat,h.lng]).addTo(map);m.bindPopup('Hospital: '+h.name+' • cap '+h.capacity+'<br>Lat: '+h.lat.toFixed(4)+', Lng: '+h.lng.toFixed(4))})
    })

    // ---- Live SACHET overlays ----
    fetch('{{ url_for("api_sachet_alerts") }}').then(r=>r.json()).then(alerts=>{
    alerts.forEach(a=>{
        const clr=colorBySeverity(a.severity);
        if(a.areas){
        a.areas.forEach(ar=>{
            if(ar.polygon && ar.polygon.length>2){
            L.polygon(ar.polygon,{weight:2,opacity:.9,fillOpacity:.15,color:clr}).addTo(map)
                .bindPopup('<b>'+(a.event||a.title||'Alert')+'</b><br>'+(a.headline||'')+'<br>Coordinates: '+ar.polygon[0][0].toFixed(4)+', '+ar.polygon[0][1].toFixed(4)+'<br><small>'+(a.sent||a.pubDate||'')+'</small><br><a href="'+(a.cap_link||'#')+'" target="_blank">CAP</a>');
            }
            if(ar.circle && ar.circle.length===3){
            const [lat,lng,radkm]=ar.circle;
            L.circle([lat,lng],{radius:radkm*1000,color:clr,weight:2,fillOpacity:.1}).addTo(map)
                .bindPopup('<b>'+(a.event||a.title||'Alert')+'</b><br>'+(a.headline||'')+'<br>Center: '+lat.toFixed(4)+', '+lng.toFixed(4)+'<br><small>'+(a.sent||a.pubDate||'')+'</small><br><a href="'+(a.cap_link||'#')+'" target="_blank">CAP</a>');
            }
        })
        }
        if(a.centroid && a.centroid.length===2){
        L.circleMarker(a.centroid,{radius:7,color:clr,fillOpacity:.9}).addTo(map)
            .bindPopup('<b>'+(a.event||a.title||'Alert')+'</b><br>Severity: '+(a.severity||'n/a')+' · Urgency: '+(a.urgency||'n/a')+'<br>Coordinates: '+a.centroid[0].toFixed(4)+', '+a.centroid[1].toFixed(4)+'<br>'+(a.areaDesc||'')+'<br><small>'+(a.sent||a.pubDate||'')+'</small><br><a href="'+(a.cap_link||'#')+'" target="_blank">CAP</a>');
        }
    })
    }).catch(e=>console.error('SACHET overlay error',e));
    </script>
    {% endblock %}
    """,
    "alerts": """
    {% extends 'layout' %}
    {% block content %}
    <div class=hero>
    <div>
    <h1>Alert System</h1>
    <p>Send emergency alerts to volunteers and stakeholders via SMS/WhatsApp.</p>
    {% if not twilio_enabled %}
    <div class="alert-warning">
    <strong>Note:</strong> SMS/WhatsApp alerts are currently disabled. To enable alerts:
    <ol style="margin:10px 0">
    <li>Install Twilio: <code>pip install twilio</code></li>
    <li>Set environment variables: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM</li>
    <li>Restart the application</li>
    </ol>
    </div>
    {% endif %}
    </div>
    <div class=card>
    <h2>Send Alert</h2>
    <form method=post class=form>
    <label>Recipient Type:</label>
    <select name="recipient_type" class=input required onchange="togglePhoneInput(this.value)">
    <option value="">Select recipient type</option>
    <option value="all_volunteers">All Volunteers</option>
    <option value="volunteer">Specific Volunteer (by phone)</option>
    <option value="phone_number">Custom Phone Number</option>
    </select>
    
    <div id="phone_input" style="display:none">
    <label>Phone Number:</label>
    <input type="tel" name="phone" class=input placeholder="+1234567890">
    </div>
    
    <label>Message:</label>
    <textarea name="message" class=input rows="4" placeholder="Enter your alert message..." required></textarea>
    
    <button type="submit" class=button {% if not twilio_enabled %}disabled{% endif %}>
    {% if twilio_enabled %}Send Alert{% else %}Alerts Disabled{% endif %}
    </button>
    </form>
    </div>
    </div>
    
    <div class=card>
    <h2>Recent SACHET Alerts</h2>
    {% if sachet_alerts %}
    <div style="max-height:400px;overflow-y:auto">
    {% for alert in sachet_alerts[:10] %}
    <div class=card style="margin:10px 0;padding:10px">
    <strong>{{ alert.event or alert.title or 'Alert' }}</strong>
    <span class="status" style="float:right">{{ alert.severity or 'Unknown' }}</span>
    <p>{{ alert.headline or alert.description or 'No description' }}</p>
    <small>{{ alert.sent or alert.pubDate or '' }} | {{ alert.areaDesc or '' }}</small>
    </div>
    {% endfor %}
    </div>
    {% else %}
    <p>No recent alerts available.</p>
    {% endif %}
    </div>

    <script>
    function togglePhoneInput(value) {
        const phoneDiv = document.getElementById('phone_input');
        if (value === 'volunteer' || value === 'phone_number') {
            phoneDiv.style.display = 'block';
        } else {
            phoneDiv.style.display = 'none';
        }
    }
    </script>
    {% endblock %}
    """,
    "report_incident": """
    {% extends 'layout' %}
    {% block content %}
    <div class=hero>
    <div>
    <h1>Report an Incident</h1>
    <p>Submit a new incident report, including type, severity, and location. This will be added to the live map and incident list for dispatch.</p>
    </div>
    <div class=card>
    <h2>New Incident Report</h2>
    <form method=post class=form>
    <label>Type of Incident:</label>
    <select name="type" class=input required>
    <option value="Debris Removal">Debris Removal</option>
    <option value="Medical Aid">Medical Aid</option>
    <option value="Shelter Request">Shelter Request</option>
    <option value="Search & Rescue">Search & Rescue</option>
    <option value="Resource Request">Resource Request</option>
    </select>
    <label>Severity:</label>
    <select name="severity" class=input required>
    <option value="1">1 (Low)</option>
    <option value="2">2</option>
    <option value="3">3</option>
    <option value="4">4</option>
    <option value="5">5 (High)</option>
    </select>
    <label>Location (Latitude, Longitude):</label>
    <div style="display:flex;gap:.5rem">
    <input type="number" step="any" name="lat" class=input placeholder="Latitude" required>
    <input type="number" step="any" name="lng" class=input placeholder="Longitude" required>
    </div>
    <button type="submit" class=button>Submit Report</button>
    </form>
    </div>
    </div>
    {% endblock %}
    """,
    "assign_tasks": """
    {% extends 'layout' %}
    {% block content %}
    <div class=hero>
    <div>
    <h1>Assign & Coordinate</h1>
    <p>View open incidents and available volunteers, then assign tasks to streamline the response effort.</p>
    </div>
    <div class=card>
    <h2>Open Incidents</h2>
    {% if incidents %}
    <table class=table>
    <tr><th>ID</th><th>Type</th><th>Severity</th><th>Lat</th><th>Lng</th><th>Reported</th><th>Assign</th></tr>
    {% for i in incidents %}
    <tr><td>{{ i['id'] }}</td><td>{{ i['type'] }}</td><td>{{ i['severity'] }}</td><td>{{ '%.4f'|format(i['lat']) }}</td><td>{{ '%.4f'|format(i['lng']) }}</td><td>{{ i['reported_at'] }}</td><td>
    <form action="{{ url_for('assign_tasks') }}" method="post" style="display:inline">
    <input type="hidden" name="incident_id" value="{{ i['id'] }}">
    <select name="volunteer_id" class=input style="width:auto;display:inline">
    {% for v in volunteers %}
    <option value="{{ v['id'] }}">{{ v['name'] }} ({{ v['phone'] or 'N/A' }})</option>
    {% endfor %}
    </select>
    <button type="submit" class="button alt" style="margin-left:.5rem">Assign</button>
    </form>
    </td></tr>
    {% endfor %}
    </table>
    {% else %}
    <p>No open incidents at this time.</p>
    {% endif %}
    </div>
    {% endblock %}
    """,
    "volunteer_tasks": """
    {% extends 'layout' %}
    {% block content %}
    <h1>My Assigned Tasks</h1>
    <p>Here are the incidents that have been assigned to you. Update the status as you complete the work.</p>
    <div class=grid cards>
    {% for task in tasks %}
    <div class=card>
    <h2>Incident #{{ task.incident.id }}</h2>
    <p><strong>Type:</strong> {{ task.incident.type }}</p>
    <p><strong>Severity:</strong> {{ task.incident.severity }}</p>
    <p><strong>Location:</strong> {{ '%.4f'|format(task.incident.lat) }}, {{ '%.4f'|format(task.incident.lng) }}</p>
    <p><strong>Status:</strong> <span class="status {{ task.status }}">{{ task.status }}</span></p>
    <p>Assigned on: {{ task.created_at }}</p>
    <form method="post" action="{{ url_for('update_task_status') }}" class="form" style="margin-top:1rem">
    <input type="hidden" name="task_id" value="{{ task.id }}">
    <label>Update Status:</label>
    <select name="status" class=input required>
    <option value="open" {% if task.status=='open' %}selected{% endif %}>Open</option>
    <option value="in_progress" {% if task.status=='in_progress' %}selected{% endif %}>In Progress</option>
    <option value="closed" {% if task.status=='closed' %}selected{% endif %}>Closed</option>
    </select>
    <button type="submit" class=button>Update</button>
    </form>
    </div>
    {% else %}
    <div class=card>
    <p>You have no assigned tasks at this time. Thank you for your readiness to help!</p>
    </div>
    {% endfor %}
    </div>
    {% endblock %}
    """,
    "resources": """
    {% extends 'layout' %}
    {% block content %}
    <div class=hero>
    <div>
    <h1>Resource Management</h1>
    <p>Track and manage available resources like heavy machinery, medical supplies, and food kits. Keep the inventory up to date for rapid deployment.</p>
    </div>
    <div class=card>
    <h2>Add New Resource</h2>
    <form method=post class=form>
    <label>Type:</label>
    <input name="type" class=input placeholder="e.g., Water Bottles, Earthmovers, Medical Kits" required>
    <label>Quantity:</label>
    <input type="number" name="qty" class=input placeholder="e.g., 500, 3, 200" required>
    <label>Location:</label>
    <input name="location" class=input placeholder="e.g., Central Warehouse, Sector-18" required>
    <button type="submit" class=button>Add Resource</button>
    </form>
    </div>
    </div>
    <div class=card>
    <h2>Current Resources</h2>
    <table class=table>
    <tr><th>ID</th><th>Type</th><th>Quantity</th><th>Location</th><th>Actions</th></tr>
    {% for r in resources %}
    <tr><td>{{ r['id'] }}</td><td>{{ r['type'] }}</td><td>{{ r['qty'] }}</td><td>{{ r['location'] }}</td><td>
    <form method="post" action="{{ url_for('delete_resource', resource_id=r['id']) }}" style="display:inline">
    <button type="submit" class="button alt" onclick="return confirm('Are you sure you want to delete this resource?')" style="background:var(--danger);color:#fff;border:none">Delete</button>
    </form>
    </td></tr>
    {% endfor %}
    </table>
    </div>
    {% endblock %}
    """,
    "predict": """
    {% extends 'layout' %}
    {% block content %}
    <div class=hero>
    <div>
    <h1>Debris Risk Map</h1>
    <p>This map shows predicted areas of high debris accumulation based on incident reports, geological data, and real-time weather alerts. Use this to pre-position resources.</p>
    <div class=card>
    <h3>How it works:</h3>
    <p style="color:var(--muted);font-size:.9rem">The map uses a "heat map" to visualize areas with a high density of reported incidents. The more incidents in an area, the "hotter" the color, indicating a higher probability of debris and a greater need for cleanup and resources.</p>
    </div>
    </div>
    <div class=card>
    <div id=map class=map></div>
    <div id="coordinates" class="coordinates-display">Lat: 0.0000, Lng: 0.0000</div>
    </div>
    </div>
    <script>
    var map=L.map('map').setView([23.5,80.0],5)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map)

    map.on('mousemove', function(e) {
        document.getElementById('coordinates').innerText = 'Lat: ' + e.latlng.lat.toFixed(4) + ', Lng: ' + e.latlng.lng.toFixed(4);
    });

    fetch('{{ url_for("api_hotspots") }}').then(r=>r.json()).then(d=>{
    if(window.L.heatLayer){L.heatLayer(d.map(p=>[p.lat,p.lng,p.w]),{radius:25,blur:15,maxZoom:17}).addTo(map)}
    })
    </script>
    {% endblock %}
    """
}

# Make inline templates available to Jinja
app.jinja_loader = DictLoader(html_base)

# ---------------- Database ----------------
def db():
    return sqlite3.connect(DB)

def init_db():
    con = db(); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,role TEXT,contact TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY,type TEXT,severity INTEGER,lat REAL,lng REAL,status TEXT,reported_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS volunteers(id INTEGER PRIMARY KEY,name TEXT,phone TEXT,lat REAL,lng REAL,available INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY,type TEXT,qty INTEGER,location TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS hospitals(id INTEGER PRIMARY KEY,name TEXT,lat REAL,lng REAL,capacity INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS shelters(id INTEGER PRIMARY KEY,name TEXT,lat REAL,lng REAL,capacity INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,incident_id INTEGER,volunteer_id INTEGER,resource_id INTEGER,status TEXT,created_at TEXT)")
    
    # Ensure contact column exists (in case of old DB)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN contact TEXT")
    except Exception:
        pass
    
    # Ensure volunteers table has phone column
    try:
        cur.execute("ALTER TABLE volunteers ADD COLUMN phone TEXT")
    except Exception:
        pass
        
    con.commit()
    
    # Seed defaults
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO users(username,password_hash,role,contact) VALUES(?,?,?,?)",
                    ("admin", sha256("admin123".encode()).hexdigest(), "admin", "+1234567890"))
        cur.execute("INSERT INTO users(username,password_hash,role,contact) VALUES(?,?,?,?)",
                    ("reporter1", sha256("reporter123".encode()).hexdigest(), "reporter", "+1234567891"))
        cur.execute("INSERT INTO users(username,password_hash,role,contact) VALUES(?,?,?,?)",
                    ("volunteer1", sha256("volunteer123".encode()).hexdigest(), "volunteer", "+1234567892"))
        cur.execute("INSERT INTO users(username,password_hash,role,contact) VALUES(?,?,?,?)",
                    ("viewer1", sha256("viewer123".encode()).hexdigest(), "viewer", ""))
        cur.execute("INSERT INTO users(username,password_hash,role,contact) VALUES(?,?,?,?)",
                    ("coordinator1", sha256("coord123".encode()).hexdigest(), "coordinator", "+1234567893"))
    
    cur.execute("SELECT COUNT(*) FROM hospitals")
    if cur.fetchone()[0] == 0:
        hospitals=[("AIIMS Rishikesh",30.153,78.292,800),("KGMU Lucknow",26.872,80.934,1200),
                ("Apollo Delhi",28.544,77.281,900),("CMC Vellore",12.926,79.133,1000),
                ("PGIMER Chandigarh",30.764,76.773,1100)]
        cur.executemany("INSERT INTO hospitals(name,lat,lng,capacity) VALUES(?,?,?,?)", hospitals)
    
    cur.execute("SELECT COUNT(*) FROM shelters")
    if cur.fetchone()[0] == 0:
        shelters=[("Dehradun Stadium",30.316,78.032,2000),("Lucknow Expo",26.846,80.946,1500),
                ("Noida Indoor",28.535,77.391,1800),("Mumbai NSS Hall",19.076,72.877,2200)]
        cur.executemany("INSERT INTO shelters(name,lat,lng,capacity) VALUES(?,?,?,?)", shelters)
    
    cur.execute("SELECT COUNT(*) FROM volunteers")
    if cur.fetchone()[0] == 0:
        vols=[("Aarav","+919000000011",28.61,77.21,1),("Diya","+919000000012",26.85,80.95,1),
            ("Kabir","+919000000013",30.32,78.03,1),("Meera","+919000000014",19.08,72.88,1)]
        cur.executemany("INSERT INTO volunteers(name,phone,lat,lng,available) VALUES(?,?,?,?,?)", vols)
    
    cur.execute("SELECT COUNT(*) FROM incidents")
    if cur.fetchone()[0] == 0:
        incidents = [
            ("Debris Removal", 4, 28.62, 77.22, "open", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("Medical Aid", 5, 26.86, 80.96, "open", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("Shelter Request", 3, 30.33, 78.04, "closed", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("Search & Rescue", 5, 28.53, 77.39, "in_progress", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("Resource Request", 2, 19.09, 72.89, "open", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ]
        cur.executemany("INSERT INTO incidents (type, severity, lat, lng, status, reported_at) VALUES (?, ?, ?, ?, ?, ?)", incidents)
    
    cur.execute("SELECT COUNT(*) FROM resources")
    if cur.fetchone()[0] == 0:
        resources = [
            ("Earthmover", 2, "Central Warehouse"),
            ("Medical Kits", 50, "Mobile Unit 1"),
            ("Food Kits", 200, "Central Warehouse")
        ]
        cur.executemany("INSERT INTO resources (type, qty, location) VALUES (?, ?, ?)", resources)

    con.commit(); con.close()

init_db()

# ---------------- Helpers ----------------
def logged_in():
    return session.get("user") is not None

def send_sms_alert(phone_number, message, use_whatsapp=False):
    """Send SMS or WhatsApp alert using Twilio"""
    if not twilio_client:
        print(f"Alert not sent (Twilio not configured): {phone_number} - {message}")
        return False, "Twilio not configured"
    
    try:
        # Format phone number
        if use_whatsapp and not phone_number.startswith('whatsapp:'):
            phone_number = f"whatsapp:{phone_number}"
        
        # Choose the appropriate sender number
        from_number = TWILIO_WHATSAPP_FROM if use_whatsapp else TWILIO_SMS_FROM
        if not from_number:
            return False, "No sender number configured"
        
        message_obj = twilio_client.messages.create(
            body=message,
            from_=from_number,
            to=phone_number
        )
        
        alert_type = "WhatsApp" if use_whatsapp else "SMS"
        print(f"{alert_type} alert sent to {phone_number}: {message_obj.sid}")
        return True, f"{alert_type} sent successfully"
        
    except Exception as e:
        error_msg = f"Error sending alert: {str(e)}"
        print(error_msg)
        return False, error_msg

def _fetch_sachet_feed():
    """Fetch SACHET alerts from NDMA feed (mocked for this example)"""
    return [
        {
            'event': 'Heavy Rainfall Alert',
            'severity': 'Moderate',
            'headline': 'Heavy to very heavy rainfall expected',
            'sent': '2025-08-26T10:30:00Z',
            'areaDesc': 'Delhi, NCR region',
            'centroid': [28.6139, 77.2090],
            'cap_link': 'https://example.com/cap/1'
        },
        {
            'event': 'Flood Warning',
            'severity': 'Severe',
            'headline': 'River levels rising, flooding possible',
            'sent': '2025-08-26T08:15:00Z',
            'areaDesc': 'Uttarakhand, Dehradun district',
            'centroid': [30.3165, 78.0322],
            'cap_link': 'https://example.com/cap/2'
        },
        {
            'event': 'Tornado Warning',
            'severity': 'Extreme',
            'headline': 'Tornado sighted, seek shelter immediately',
            'sent': '2025-08-26T12:00:00Z',
            'areaDesc': 'Uttar Pradesh, Lucknow district',
            'centroid': [26.8465, 80.9463],
            'cap_link': 'https://example.com/cap/3'
        }
    ]

# ---------------- Decorators for Access Control ----------------
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrap

def roles_required(roles):
    def decorator(f):
        @wraps(f)
        def wrap(*args, **kwargs):
            if not logged_in() or session["user"]["role"] not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrap
    return decorator

# ---------------- Routes ----------------
@app.route("/")
def index():
    if not logged_in():
        return redirect(url_for("login"))
    
    user_role = session["user"]["role"]
    if user_role in ["admin", "reporter", "coordinator", "viewer"]:
        return redirect(url_for("dashboard"))
    elif user_role == "volunteer":
        return redirect(url_for("volunteer_tasks"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username","")
        p = request.form.get("password","")
        con = db(); cur = con.cursor()
        cur.execute("SELECT id,username,password_hash,role,contact FROM users WHERE username=?", (u,))
        row = cur.fetchone(); con.close()
        if row and sha256(p.encode()).hexdigest()==row[2]:
            session["user"]={"id":row[0],"username":row[1],"role":row[3], "contact":row[4]}
            return redirect(url_for("index"))
        else:
            return render_template_string(html_base["login"], message="Invalid credentials")
    return render_template_string(html_base["login"], message=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        role = request.form.get("role","").strip()
        contact = request.form.get("contact","").strip()
        
        if not username or not password or not role:
            return render_template_string(html_base["register"], title="Register", active="",
                                          message_sent=("error", "All fields except contact are required"),
                                          now=datetime.now().strftime("%Y-%m-%d %H:%M"))
        
        con = db(); cur = con.cursor()
        try:
            cur.execute("INSERT INTO users(username,password_hash,role,contact) VALUES(?,?,?,?)",
                        (username, sha256(password.encode()).hexdigest(), role, contact))
            con.commit()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return render_template_string(html_base["register"], title="Register", active="",
                                          message_sent=("error", "Username already exists"),
                                          now=datetime.now().strftime("%Y-%m-%d %H:%M"))
        finally:
            con.close()
    
    return render_template_string(html_base["register"], title="Register", active="",
                                  now=datetime.now().strftime("%Y-%m-%d %H:%M"))

@app.route("/dashboard")
@login_required
@roles_required(['admin', 'reporter', 'coordinator', 'viewer'])
def dashboard():
    con = db(); cur = con.cursor()
    
    # Get KPIs
    cur.execute("SELECT COUNT(*) FROM incidents")
    total_incidents = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM incidents WHERE status='open'")
    open_incidents = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM volunteers WHERE available=1")
    volunteers = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM resources")
    resources = cur.fetchone()[0]
    
    # Get recent incidents
    cur.execute("SELECT * FROM incidents ORDER BY reported_at DESC LIMIT 10")
    incidents = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    
    con.close()
    
    kpis = {
        'total_incidents': total_incidents,
        'open_incidents': open_incidents,
        'volunteers': volunteers,
        'resources': resources
    }
    
    return render_template_string(html_base["dashboard"], title="Dashboard", active="dashboard",
                                  kpis=kpis, incidents=incidents,
                                  now=datetime.now().strftime("%Y-%m-%d %H:%M"))

@app.route("/alerts", methods=["GET", "POST"])
@login_required
@roles_required(['admin', 'coordinator'])
def alerts():
    message_sent = None
    if request.method == "POST":
        recipient_type = request.form.get("recipient_type")
        phone = request.form.get("phone", "").strip()
        message = request.form.get("message", "").strip()
        
        if not message:
            message_sent = ("error", "Message cannot be empty")
        elif not twilio_client:
            message_sent = ("warning", "Twilio not configured. Alert simulation: would have sent to specified recipients.")
        else:
            con = db(); cur = con.cursor()
            
            if recipient_type == "volunteer" and phone:
                # Send to specific volunteer by phone
                success, msg = send_sms_alert(phone, message, use_whatsapp=True)
                message_sent = ("success" if success else "error", msg)
            
            elif recipient_type == "phone_number" and phone:
                success, msg = send_sms_alert(phone, message, use_whatsapp=False)
                message_sent = ("success" if success else "error", msg)
            
            elif recipient_type == "all_volunteers":
                # Send to all volunteers
                cur.execute("SELECT phone FROM volunteers WHERE phone IS NOT NULL AND phone != ''")
                volunteers = cur.fetchall()
                
                if not volunteers:
                    message_sent = ("error", "No volunteers with phone numbers found")
                else:
                    sent_count = 0
                    failed_count = 0
                    for vol in volunteers:
                        success, _ = send_sms_alert(vol[0], message, use_whatsapp=True)
                        if success:
                            sent_count += 1
                        else:
                            failed_count += 1
                    
                    if sent_count > 0:
                        msg = f"Alert sent to {sent_count} volunteers"
                        if failed_count > 0:
                            msg += f" ({failed_count} failed)"
                        message_sent = ("success", msg)
                    else:
                        message_sent = ("error", f"Failed to send alerts to all {len(volunteers)} volunteers")
            
            elif recipient_type == "all_users":
                # Send to all users with contact info
                cur.execute("SELECT contact FROM users WHERE contact IS NOT NULL AND contact != ''")
                users = cur.fetchall()
                if not users:
                    message_sent = ("error", "No users with contact numbers found")
                else:
                    sent_count = 0
                    failed_count = 0
                    for user in users:
                        success, _ = send_sms_alert(user[0], message, use_whatsapp=False) # Default to SMS
                        if success:
                            sent_count += 1
                        else:
                            failed_count += 1
                    msg = f"Alert sent to {sent_count} users"
                    if failed_count > 0:
                        msg += f" ({failed_count} failed)"
                    message_sent = ("success", msg)
            
            con.close()
            
    sachet_alerts = _fetch_sachet_feed()
    
    return render_template_string(html_base["alerts"], title="Alerts", active="alerts",
                                  twilio_enabled=bool(twilio_client), sachet_alerts=sachet_alerts,
                                  message_sent=message_sent, now=datetime.now().strftime("%Y-%m-%d %H:%M"))

@app.route("/report", methods=["GET", "POST"])
@login_required
@roles_required(['admin', 'reporter'])
def report_incident():
    message_sent = None
    if request.method == "POST":
        incident_type = request.form.get("type")
        severity = int(request.form.get("severity"))
        lat = float(request.form.get("lat"))
        lng = float(request.form.get("lng"))
        
        con = db(); cur = con.cursor()
        cur.execute("INSERT INTO incidents(type, severity, lat, lng, status, reported_at) VALUES(?,?,?,?,?,?)",
                    (incident_type, severity, lat, lng, "open", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        con.commit(); con.close()
        
        message_sent = ("success", "Incident reported successfully!")
    
    return render_template_string(html_base["report_incident"], title="Report Incident", active="report",
                                  message_sent=message_sent, now=datetime.now().strftime("%Y-%m-%d %H:%M"))

@app.route("/assign_tasks", methods=["GET", "POST"])
@login_required
@roles_required(['admin', 'coordinator'])
def assign_tasks():
    message_sent = None
    con = db(); cur = con.cursor()
    
    if request.method == "POST":
        incident_id = request.form.get("incident_id")
        volunteer_id = request.form.get("volunteer_id")
        
        cur.execute("SELECT * FROM incidents WHERE id=?", (incident_id,))
        incident = cur.fetchone()
        
        cur.execute("SELECT * FROM volunteers WHERE id=?", (volunteer_id,))
        volunteer = cur.fetchone()
        
        if incident and volunteer:
            try:
                # Assign the task
                cur.execute("INSERT INTO tasks(incident_id, volunteer_id, status, created_at) VALUES(?,?,?,?)",
                            (incident_id, volunteer_id, "assigned", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                
                # Update incident status to 'in_progress'
                cur.execute("UPDATE incidents SET status=? WHERE id=?", ("in_progress", incident_id))
                con.commit()
                
                # Send alert to volunteer (if Twilio is configured)
                if twilio_client and volunteer[2]:
                    alert_msg = f"New Task Assigned! Incident ID: {incident_id}. Type: {incident[1]}. Location: {incident[3]:.4f}, {incident[4]:.4f}. Please check the app for details."
                    send_sms_alert(volunteer[2], alert_msg, use_whatsapp=True)
                
                message_sent = ("success", f"Incident #{incident_id} assigned to {volunteer[1]}.")
            except Exception as e:
                con.rollback()
                message_sent = ("error", f"Failed to assign task: {e}")
        else:
            message_sent = ("error", "Incident or Volunteer not found.")

    cur.execute("SELECT * FROM incidents WHERE status IN ('open', 'in_progress') ORDER BY severity DESC")
    incidents = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    
    cur.execute("SELECT * FROM volunteers WHERE available=1")
    volunteers = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    
    con.close()
    
    return render_template_string(html_base["assign_tasks"], title="Assign Tasks", active="assign",
                                  incidents=incidents, volunteers=volunteers,
                                  message_sent=message_sent, now=datetime.now().strftime("%Y-%m-%d %H:%M"))

@app.route("/volunteer_tasks", methods=["GET", "POST"])
@login_required
@roles_required(['volunteer'])
def volunteer_tasks():
    con = db(); cur = con.cursor()
    
    # Get all tasks for the current volunteer
    cur.execute("SELECT * FROM tasks WHERE volunteer_id=? ORDER BY created_at DESC", (session["user"]["id"],))
    tasks_raw = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    
    tasks = []
    for task in tasks_raw:
        cur.execute("SELECT * FROM incidents WHERE id=?", (task['incident_id'],))
        incident = cur.fetchone()
        if incident:
            incident_dict = dict(zip([col[0] for col in cur.description], incident))
            task['incident'] = incident_dict
            tasks.append(task)
            
    con.close()
    
    return render_template_string(html_base["volunteer_tasks"], title="My Tasks", active="tasks",
                                  tasks=tasks, now=datetime.now().strftime("%Y-%m-%d %H:%M"))

@app.route("/update_task_status", methods=["POST"])
@login_required
@roles_required(['volunteer'])
def update_task_status():
    task_id = request.form.get("task_id")
    status = request.form.get("status")
    
    con = db(); cur = con.cursor()
    cur.execute("UPDATE tasks SET status=? WHERE id=? AND volunteer_id=?", (status, task_id, session["user"]["id"]))
    con.commit()
    
    # Update incident status if task is completed
    cur.execute("SELECT incident_id FROM tasks WHERE id=?", (task_id,))
    incident_id = cur.fetchone()[0]
    if status == 'closed':
        cur.execute("UPDATE incidents SET status=? WHERE id=?", ("closed", incident_id))
    elif status == 'in_progress':
        cur.execute("UPDATE incidents SET status=? WHERE id=?", ("in_progress", incident_id))
    elif status == 'open':
        cur.execute("UPDATE incidents SET status=? WHERE id=?", ("open", incident_id))
    con.commit(); con.close()
    
    return redirect(url_for("volunteer_tasks"))

@app.route("/resources", methods=["GET", "POST"])
@login_required
@roles_required(['admin', 'coordinator'])
def resources():
    message_sent = None
    if request.method == "POST":
        resource_type = request.form.get("type")
        qty = request.form.get("qty")
        location = request.form.get("location")
        
        con = db(); cur = con.cursor()
        cur.execute("INSERT INTO resources(type, qty, location) VALUES(?,?,?)", (resource_type, qty, location))
        con.commit(); con.close()
        
        message_sent = ("success", "Resource added successfully!")
        
    con = db(); cur = con.cursor()
    cur.execute("SELECT * FROM resources ORDER BY type")
    resources_list = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    con.close()
    
    return render_template_string(html_base["resources"], title="Resources", active="resources",
                                  resources=resources_list, message_sent=message_sent,
                                  now=datetime.now().strftime("%Y-%m-%d %H:%M"))

@app.route("/resources/delete/<int:resource_id>", methods=["POST"])
@login_required
@roles_required(['admin', 'coordinator'])
def delete_resource(resource_id):
    con = db(); cur = con.cursor()
    cur.execute("DELETE FROM resources WHERE id=?", (resource_id,))
    con.commit(); con.close()
    return redirect(url_for("resources"))

@app.route("/predict")
@login_required
@roles_required(['admin', 'reporter', 'viewer'])
def predict():
    return render_template_string(html_base["predict"], title="Debris Risk Map", active="predict", now=datetime.now().strftime("%Y-%m-%d %H:%M"))

# ---------------- API Endpoints for Map Data ----------------
@app.route("/api/incidents")
def api_incidents():
    con = db(); cur = con.cursor()
    cur.execute("SELECT id, type, severity, lat, lng, status FROM incidents")
    incidents = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    con.close()
    return jsonify(incidents)

@app.route("/api/hotspots")
def api_hotspots():
    con = db(); cur = con.cursor()
    # Simple hotspot logic: lat, lng, and severity as weight
    cur.execute("SELECT lat, lng, severity FROM incidents WHERE status='open' ORDER BY severity DESC")
    hotspots = [{'lat': r[0], 'lng': r[1], 'w': r[2]} for r in cur.fetchall()]
    con.close()
    return jsonify(hotspots)

@app.route("/api/hospitals")
def api_hospitals():
    con = db(); cur = con.cursor()
    cur.execute("SELECT name, lat, lng, capacity FROM hospitals")
    hospitals = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]
    con.close()
    return jsonify(hospitals)

@app.route("/api/sachet_alerts")
def api_sachet_alerts():
    # Return mock data
    return jsonify(_fetch_sachet_feed())

# ---------------- Main entry point ----------------
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)