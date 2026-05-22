# 🚀 IoT School Bell System - Quick Start Guide

Bu qo'llanma tizimni 0'dan ishga tushirish uchun.

---

## 📋 Prerequisites

```bash
# System requirements
- Ubuntu 20.04+ yoki Windows WSL2
- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- EMQX 5.0+ (MQTT broker)
```

---

## 1️⃣ EMQX Broker O'rnatish

### Ubuntu/Debian:

```bash
# EMQX repository qo'shish
curl -s https://assets.emqx.com/scripts/install-emqx-deb.sh | sudo bash

# EMQX o'rnatish
sudo apt-get install emqx

# Ishga tushirish
sudo systemctl start emqx
sudo systemctl enable emqx

# Tekshirish
sudo systemctl status emqx
```

### Docker (alternative):

```bash
docker run -d --name emqx \
  -p 1883:1883 \
  -p 18083:18083 \
  emqx/emqx:latest
```

### EMQX Dashboard:

- URL: http://localhost:18083
- Default login: `admin` / `public`

---

## 2️⃣ Backend O'rnatish

```bash
# 1. Clone repository
cd /var/www/
git clone <your-repo> iot-backend
cd iot-backend

# 2. Virtual environment
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt
# yoki uv bilan:
uv pip install -e .

# 4. Environment variables
cp .env.iot.example .env
nano .env  # Edit qiling
```

### .env fayl (minimal):

```env
SECRET_KEY=your-very-secret-key-here
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=iot_devices
POSTGRES_USER=iot_user
POSTGRES_PASSWORD=secure_password_123
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
MQTT_USERNAME=django_backend
MQTT_PASSWORD=mqtt_secure_pass

CELERY_BROKER_URL=redis://localhost:6379/0
REDIS_URL=redis://localhost:6379/1
```

---

## 3️⃣ Database Setup

```bash
# PostgreSQL yaratish
sudo -u postgres psql

postgres=# CREATE DATABASE iot_devices;
postgres=# CREATE USER iot_user WITH PASSWORD 'secure_password_123';
postgres=# GRANT ALL PRIVILEGES ON DATABASE iot_devices TO iot_user;
postgres=# \q

# Django migrations
cd src
python manage.py makemigrations
python manage.py migrate

# Superuser yaratish
python manage.py createsuperuser
# Email: admin@school.uz
# Password: ***
```

---

## 4️⃣ MQTT Authentication Setup (EMQX)

### Option 1: Built-in Database (Simple)

1. EMQX Dashboard'ga kiring: http://localhost:18083
2. **Authentication** → **Create** → **Built-in Database**
3. **Add User**:
   - Username: `django_backend`
   - Password: `mqtt_secure_pass`
4. Yana bir user:
   - Username: `django_listener`
   - Password: `mqtt_secure_pass`

### Option 2: PostgreSQL (Production)

EMQX config (`/etc/emqx/emqx.conf`):

```hocon
authentication {
  mechanism = password_based
  backend = postgresql
  server = "localhost:5432"
  database = "iot_devices"
  username = "iot_user"
  password = "secure_password_123"
  query = "SELECT mqtt_password_hash AS password FROM devices WHERE device_id = ${username} LIMIT 1"
  password_hash_algorithm {
    name = sha256
    salt_position = suffix
  }
}
```

---

## 5️⃣ MQTT ACL (Authorization)

EMQX Dashboard → **Authorization** → **File** → Edit:

```erlang
%% Backend full access
{allow, {user, "django_backend"}, all, ["#"]}.
{allow, {user, "django_listener"}, subscribe, ["object/diagnostics", "object/+/ota_status"]}.

%% Devices restricted access
{allow, all, subscribe, ["object/${clientid}/cmd"]}.
{allow, all, publish, ["object/diagnostics", "object/${clientid}/ota_status"]}.

%% Deny all else
{deny, all}.
```

EMQX'ni restart qiling:

```bash
sudo systemctl restart emqx
```

---

## 6️⃣ Services Ishga Tushirish

### Terminal 1: Django Development Server

```bash
cd src
python manage.py runserver 0.0.0.0:8000
```

### Terminal 2: MQTT Listener

```bash
cd src
python apps/devices/services/mqtt_listener.py
```

### Terminal 3: Celery Worker

```bash
cd src
celery -A core worker -l info
```

### Terminal 4: Celery Beat (Scheduler)

```bash
cd src
celery -A core beat -l info
```

### Yoki Production (systemd):

**Django (Gunicorn):**

```bash
sudo nano /etc/systemd/system/django-iot.service
```

```ini
[Unit]
Description=Django IoT Backend
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/iot-backend/src
Environment="PATH=/var/www/iot-backend/venv/bin"
EnvironmentFile=/var/www/iot-backend/.env
ExecStart=/var/www/iot-backend/venv/bin/gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 4

[Install]
WantedBy=multi-user.target
```

**MQTT Listener:**

```bash
sudo cp deployments/mqtt-listener.service /etc/systemd/system/
sudo systemctl enable mqtt-listener
sudo systemctl start mqtt-listener
```

**Celery:**

```bash
sudo nano /etc/systemd/system/celery-worker.service
```

```ini
[Unit]
Description=Celery Worker
After=network.target

[Service]
Type=forking
User=www-data
WorkingDirectory=/var/www/iot-backend/src
Environment="PATH=/var/www/iot-backend/venv/bin"
EnvironmentFile=/var/www/iot-backend/.env
ExecStart=/var/www/iot-backend/venv/bin/celery -A core worker --detach --loglevel=info

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable celery-worker
sudo systemctl start celery-worker
```

---

## 7️⃣ Test qilish

### 1. Django Admin

```
http://localhost:8000/admin/
Login: admin@school.uz
```

### 2. API Swagger

```
http://localhost:8000/api/schema/swagger-ui/
```

### 3. MQTT Test (MQTTX yoki mosquitto_pub)

```bash
# Diagnostika yuborish (simulate ESP8266)
mosquitto_pub -h localhost -p 1883 \
  -t "object/diagnostics" \
  -m '{"id":"test_device","fw":"1.0.0","rtc":"ok","rssi":-60,"heap":32000}'

# Admin panel'da device paydo bo'lishi kerak!
```

### 4. Ring Command Test

```bash
# API orqali
curl -X POST http://localhost:8000/api/v1/devices/1/ring/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"duration": 5}'

# MQTT orqali eshitish kerak:
mosquitto_sub -h localhost -p 1883 -t "object/test_device/cmd"
# Output: {"cmd":"ring","dur":5}
```

---

## 8️⃣ ESP8266 Firmware (Arduino)

### Arduino IDE Setup:

1. **File → Preferences → Additional Board URLs:**
   ```
   http://arduino.esp8266.com/stable/package_esp8266com_index.json
   ```
2. **Tools → Board → ESP8266 Boards → NodeMCU 1.0**
3. **Libraries:**
   - `PubSubClient` (MQTT)
   - `ArduinoJson`
   - `RTClib` (DS3231)
   - `ESP8266httpUpdate` (OTA)

### Minimal Kod:

```cpp
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

const char* ssid = "YOUR_WIFI";
const char* password = "YOUR_PASSWORD";
const char* mqtt_server = "192.168.1.100";  // Backend IP
const char* device_id = "device_001";

WiFiClient espClient;
PubSubClient client(espClient);

void setup() {
  Serial.begin(115200);

  // WiFi connect
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  // MQTT connect
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  // Subscribe
  String cmdTopic = "object/" + String(device_id) + "/cmd";
  client.subscribe(cmdTopic.c_str());
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // Har 60 sekundda diagnostika
  static unsigned long lastMsg = 0;
  if (millis() - lastMsg > 60000) {
    lastMsg = millis();
    sendDiagnostics();
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  deserializeJson(doc, payload, length);

  if (doc.containsKey("cmd")) {
    if (doc["cmd"] == "ring") {
      int duration = doc["dur"];
      // Buzzer logic
      digitalWrite(BUZZER_PIN, HIGH);
      delay(duration * 1000);
      digitalWrite(BUZZER_PIN, LOW);
    }
  }

  if (doc.containsKey("times")) {
    // Schedule saqlash
    JsonArray times = doc["times"];
    // LittleFS'ga yozish
  }
}

void sendDiagnostics() {
  StaticJsonDocument<256> doc;
  doc["id"] = device_id;
  doc["fw"] = "1.0.0";
  doc["rtc"] = "ok";
  doc["rssi"] = WiFi.RSSI();
  doc["heap"] = ESP.getFreeHeap();

  char buffer[256];
  serializeJson(doc, buffer);

  client.publish("object/diagnostics", buffer);
}

void reconnect() {
  while (!client.connected()) {
    if (client.connect(device_id)) {
      String cmdTopic = "object/" + String(device_id) + "/cmd";
      client.subscribe(cmdTopic.c_str());
    } else {
      delay(5000);
    }
  }
}
```

Upload qiling va Serial Monitor'da loglarni ko'ring!

---

## 9️⃣ Production Deployment

### Nginx Reverse Proxy:

```bash
sudo nano /etc/nginx/sites-available/iot-backend
```

```nginx
server {
    listen 80;
    server_name iot.school.uz;

    client_max_body_size 10M;  # Firmware upload uchun

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /media/ {
        alias /var/www/iot-backend/media/;
    }

    location /static/ {
        alias /var/www/iot-backend/static/;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/iot-backend /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### SSL (Let's Encrypt):

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d iot.school.uz
```

---

## 🔟 Monitoring

### Prometheus + Grafana:

```bash
# Django prometheus metrics
http://localhost:8000/metrics

# EMQX metrics
http://localhost:18083/api/v5/metrics
```

### Health Checks:

```bash
# Django
curl http://localhost:8000/api/v1/devices/stats/

# MQTT
mosquitto_pub -h localhost -t "test" -m "ping"

# Database
psql -U iot_user -d iot_devices -c "SELECT COUNT(*) FROM devices;"

# Celery
celery -A core inspect active
```

---

## ✅ Verification Checklist

- [ ] Django admin works (http://localhost:8000/admin/)
- [ ] API responds (http://localhost:8000/api/v1/devices/)
- [ ] MQTT listener logs incoming messages
- [ ] Celery beat tasks running (check logs)
- [ ] Test device appears in admin after diagnostics
- [ ] Ring command works via API
- [ ] Schedule syncs to MQTT topic
- [ ] EMQX dashboard shows connected clients

---

## 🆘 Troubleshooting

### MQTT connection failed

```bash
# Check EMQX status
sudo systemctl status emqx

# Check authentication
sudo emqx ctl authentication list

# Test connection
mosquitto_pub -h localhost -p 1883 -u django_backend -P mqtt_secure_pass -t test -m hello
```

### Database connection error

```bash
# Check PostgreSQL
sudo systemctl status postgresql
sudo -u postgres psql -c "\l"

# Test connection
psql -U iot_user -d iot_devices -h localhost
```

### Celery tasks not running

```bash
# Check Redis
redis-cli ping  # Should return PONG

# Check Celery
celery -A core inspect active
celery -A core inspect scheduled
```

---

## 📚 Next Steps

1. **Frontend:** React yoki Vue admin panel yaratish
2. **Mobile App:** Flutter yoki React Native
3. **Analytics:** Device uptime reports, firmware adoption
4. **Alerts:** Telegram bot yoki Email notifications
5. **Backup:** Automated PostgreSQL backups
6. **Load Testing:** 10K+ device simulation

---

**Tayyor!** 🎉

Tizimingiz endi ishga tushdi. Agar savol bo'lsa, WORKFLOW.md faylini o'qing yoki hujjatlarga qarang.
