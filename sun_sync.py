import uasyncio
import sys
import json
import gc
import time
import urequests as requests  # MicroPython's version of requests

from network_manager import NetworkManager
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_7 as DISPLAY
from machine import Pin, RTC
from pimoroni_i2c import PimoroniI2C
from pcf85063a import PCF85063A
import WIFI_CONFIG
import inky_helper as ih
import ntptime

# Constants
I2C_SDA_PIN = 4
I2C_SCL_PIN = 5
HOLD_VSYS_EN_PIN = 2
UPDATE_INTERVAL = 60  # 1 minute in seconds
BLACK, WHITE, GREEN, BLUE, RED, YELLOW, ORANGE, TAUPE = range(8)
DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
fDOW = ['DOW', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

# Debug Mode
DEBUG_MODE = True  # Set to False to disable debug output

# Initialize display and other components
graphics = PicoGraphics(DISPLAY)
ih.clear_button_leds()
ih.led_warn.off()

# Initialize I2C and RTC
i2c = PimoroniI2C(I2C_SDA_PIN, I2C_SCL_PIN, 100000)
rtc = PCF85063A(i2c)

# Enable vsys hold
hold_vsys_en_pin = Pin(HOLD_VSYS_EN_PIN, Pin.OUT)
hold_vsys_en_pin.value(True)

# Load secrets
my_user_email = ""
my_user_password = ""
my_sun_serial = ""
try:
    from secrets import SUN_EMAIL, SUN_PW, SUN_SERIAL
    my_user_email = SUN_EMAIL
    my_user_password = SUN_PW
    my_sun_serial = SUN_SERIAL
except ImportError:
    print("Create a 'secrets.py' file with your SunSync credentials")
    sys.exit(1)

# Load locations from file or set default locations
locations = {}
if ih.file_exists("locations.json"):
    with open("/locations.json", "r") as f:
        locations = json.load(f)
else:
    locations = {
        'Local': ['51.507351', '-0.127758', 'LON'],
        'New York': ['40.712776', '-74.005974', 'NYC'],
        'Singapore': ['1.352083', '103.819839', 'SGP'],
        'Manchester': ['53.480759', '-2.242631', 'MAN'],
        'Malmo': ['55.604980', '13.003822', 'MMX'],
        'ListOrder': ['Manchester', 'Singapore', 'Malmo', 'New York', 'Local']
    }
    with open("/locations.json", "w") as f:
        json.dump(locations, f)

LOCAL_LOCATION = locations['Local']

# Initialize network manager
def status_handler(mode, status, ip):
    """Handle network status updates."""
    print(f"Mode: {mode}, Status: {status}, IP: {ip}")

network_manager = NetworkManager(WIFI_CONFIG.COUNTRY, status_handler=status_handler)

# API Endpoints
login_url = 'https://api.sunsynk.net/oauth/token'
plant_id_endpoint = f'https://api.sunsynk.net/api/v1/plants?page=1&limit=10&name=&status='
inverter_endpoint = f'https://api.sunsynk.net/api/v1/inverter/battery/{my_sun_serial}/realtime?sn={my_sun_serial}&lan=en'
grid_endpoint = f'https://api.sunsynk.net/api/v1/inverter/grid/{my_sun_serial}/realtime?sn={my_sun_serial}'
load_endpoint = f'https://api.sunsynk.net/api/v1/inverter/load/{my_sun_serial}/realtime?sn={my_sun_serial}'

def debug_print(message):
    """Utility function to print debug messages when DEBUG_MODE is enabled."""
    if DEBUG_MODE:
        print(message)

def print_header(local_curr_time, local_curr_temp):
    """Display the current time and weather data."""
    rtc_current = RTC()
    timestamp = rtc_current.datetime()
    dow_now = DOW[timestamp[3]] #calculate Day Of the Week for a date
    timestring1 = f"{timestamp[2]:02d}-{timestamp[1]:02d}"
    
    if (int(timestamp[4]) + 1) == 24: #adjust for UTC
        timestring2='00'
    else:
        timestring2=int(timestamp[4]) + 1
    timestring2 = f"{timestring2:02d}"
    
    timestring = f"{dow_now} {timestring1} {timestring2}:{timestamp[5]:02d}"
    print(f"{timestring} - Now")
    print(f"{local_curr_time} - Weather Data")

    graphics.set_pen(BLACK)
    graphics.rectangle(0, 0, 800, 60)
    graphics.set_font("sans")
    graphics.set_pen(WHITE)
    graphics.set_thickness(4)
    graphics.text(timestring, 15, 35, 800, 2)

    graphics.set_pen(YELLOW)
    graphics.text(f"{local_curr_temp}c", 590, 35, 800, 2)
    graphics.set_pen(BLACK)
    return 1

def my_bearer_token():
    """Retrieve and return the bearer token."""
    # Connect to WiFi
    uasyncio.get_event_loop().run_until_complete(network_manager.client(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK))

    headers = {
        'Content-type': 'application/json',
        'Accept': 'application/json'
    }

    payload = {
        "username": my_user_email,
        "password": my_user_password,
        "grant_type": "password",
        "client_id": "csp-web"
    }

    try:
        response = requests.post(login_url, json=payload, headers=headers)
        
        if response.status_code == 200:
            raw_data = response.json()
            my_access_token = raw_data["data"]["access_token"]
            global the_bearer_token_string
            the_bearer_token_string = f'Bearer {my_access_token}'

            debug_print(f"Bearer Token: {my_access_token}")
            return my_access_token
        else:
            print(f"Failed to retrieve bearer token. Status code: {response.status_code}")
            return None

    except Exception as e:
        print(f"Error retrieving bearer token: {e}")
        return None

def my_current_usage():
    """Retrieve and display current solar usage and weather information."""
    headers_and_token = {
        'Content-type': 'application/json',
        'Accept': 'application/json',
        'Authorization': the_bearer_token_string
    }

    try:
        # Fetch solar and weather data
        plant_response = requests.get(plant_id_endpoint, headers=headers_and_token)
        if plant_response.status_code == 200:
            plant_response = plant_response.json()
            debug_print(f"Plant response: {plant_response}")
        else:
            print("Error: plant_response is None")
            return

        inverter_response = requests.get(inverter_endpoint, headers=headers_and_token)
        if inverter_response.status_code == 200:
            inverter_response = inverter_response.json()
            debug_print(f"Inverter response: {inverter_response}")
        else:
            print("Error: inverter_response is None")
            return

        grid_response = requests.get(grid_endpoint, headers=headers_and_token)
        if grid_response.status_code == 200:
            grid_response = grid_response.json()
            debug_print(f"Grid response: {grid_response}")
        else:
            print("Error: grid_response is None")
            return

        load_response = requests.get(load_endpoint, headers=headers_and_token)
        if load_response.status_code == 200:
            load_response = load_response.json()
            debug_print(f"Load response: {load_response}")
        else:
            print("Error: load_response is None")
            return

        local_curr_temp_endpoint = f'https://api.open-meteo.com/v1/forecast?latitude={LOCAL_LOCATION[0]}&longitude={LOCAL_LOCATION[1]}&current=temperature_2m&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&wind_speed_unit=mph&precipitation_unit=inch&timezone=Europe%2FLondon&forecast_days=1'
        curr_temp_response = requests.get(local_curr_temp_endpoint)
        if curr_temp_response.status_code == 200:
            curr_temp_response = curr_temp_response.json()
            debug_print(f"Temperature response: {curr_temp_response}")
        else:
            print("Error: curr_temp_response is None")
            return

    except Exception as error:
        print(f"Error retrieving usage data: {error}")
        return

    gc.collect()

    if 'data' in plant_response and 'infos' in plant_response['data']:
        for plant_info in plant_response['data']['infos']:
            current_gen_w = int(plant_info['pac'])
            debug_print(f"id:{plant_info['id']}:cur:{plant_info['pac']}W:update:{plant_info['updateAt']}")

            # Ensure inverter_response['data'] exists and check for 'soc'
            if inverter_response and 'data' in inverter_response and inverter_response['data'] is not None:
                if 'soc' in inverter_response['data'] and inverter_response['data']['soc'] is not None:
                    soc = round(float(inverter_response['data']['soc']))
                else:
                    print("SOC is missing or None, using default value of 0")
                    soc = 0  # Assign default value
            else:
                print("Inverter data is missing, using default value for SOC.")
                soc = 0

            # Ensure 'power' exists before accessing it
            if inverter_response and 'data' in inverter_response and inverter_response['data'] is not None:
                if 'power' in inverter_response['data'] and inverter_response['data']['power'] is not None:
                    bat_usage = int(inverter_response['data']['power'])
                else:
                    bat_usage = 0  # Default to 0 if 'power' is missing
            else:
                bat_usage = 0  # Default to 0 if 'data' is None or missing

            # Ensure grid_response has valid data
            if grid_response and 'data' in grid_response and 'vip' in grid_response['data'] and len(grid_response['data']['vip']) > 0:
                grid_power = int(grid_response['data']['vip'][0]['power'])
            else:
                grid_power = 0  # Default to 0 if missing

            if load_response and 'data' in load_response and 'vip' in load_response['data'] and len(load_response['data']['vip']) > 0:
                load_power = int(load_response['data']['vip'][0]['power'])
            else:
                load_power = 0  # Default to 0 if missing

            if 'current' in curr_temp_response and 'temperature_2m' in curr_temp_response['current']:
                local_curr_temp = curr_temp_response['current']['temperature_2m']
            else:
                local_curr_temp = 0  # Default temperature if missing

            if 'current' in curr_temp_response and 'time' in curr_temp_response['current']:
                local_curr_time = curr_temp_response['current']['time']
            else:
                local_curr_time = "unknown"  # Default time if missing

            print_header(local_curr_time, local_curr_temp)
            display_power_data(current_gen_w, load_power, bat_usage, grid_power)
            draw_batt(soc)
            graphics.update()

    return current_gen_w


def display_power_data(current_gen_w, load_power, bat_usage, grid_power):
    """Display power generation, load, battery, and grid information."""
    pv_titles_y = 153
    pv_titles = ['Pv:', 'Ld:', 'Bt:', 'Gr:']
    for i, title in enumerate(pv_titles):
        graphics.text(title, 0, pv_titles_y + i * 100, 800, 2)

    graphics.set_font("sans")
    graphics.set_thickness(8)

    # Generated electricity
    graphics.set_pen(RED if current_gen_w < 100 else GREEN)
    graphics.text(f"{current_gen_w}W", 110, 132, 800, 4)

    # Load
    graphics.set_pen(BLACK)
    graphics.text(f"{load_power}W", 110, 232, 800, 4)

    # Battery usage
    graphics.set_pen(RED if bat_usage > 0 else GREEN)
    graphics.text(f"{abs(bat_usage)}W{'+' if bat_usage > 0 else '-'}", 110, 336, 800, 4)

    # Grid
    graphics.set_pen(BLUE if grid_power > 0 else RED)
    graphics.text(f"{abs(grid_power)}W{'-' if grid_power < 0 else ''}", 110, 440, 800, 4)

def my_current_weather(LOCATION):
    """Fetch and display the current weather for a given location."""
    headers = {
        'Content-type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Construct the weather API endpoint with the given location coordinates
    curr_temp_endpoint = f'https://api.open-meteo.com/v1/forecast?latitude={LOCATION[0]}&longitude={LOCATION[1]}&current=temperature_2m&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&wind_speed_unit=mph&precipitation_unit=inch&timezone=Europe%2FLondon&forecast_days=5'

    print(f"FULL WEATHER RUN: {LOCATION[2]}")
    
    try:
        curr_temp_req = requests.get(curr_temp_endpoint)
        if curr_temp_req.status_code == 200:
            curr_temp_response = curr_temp_req.json()
            debug_print(f"Weather response for {LOCATION[2]}: {curr_temp_response}")
        else:
            print(f"Error: Failed to fetch weather for {LOCATION[2]}")
            return
        
    except Exception as error:
        print(f"Error fetching weather data for {LOCATION[2]}: {error}")
        return

    # Extract relevant weather information
    local_curr_temp = curr_temp_response['current']['temperature_2m']
    local_curr_time = curr_temp_response['current']['time']
    
    # Display weather data using print_header
    print_header(local_curr_time, local_curr_temp)
    
    forecast_title_y = 50
    forecast_offset = 60
    hci = 0

    # Extract the RTC's current time
    rtc_current = machine.RTC()
    timestamp = rtc_current.datetime()
    first_hour = int(timestamp[4]) + 1
    last_hour = first_hour + 3

    # Display the hourly weather forecast for the next few hours
    for i in range(first_hour, last_hour):
        hci += 1
        hrfc_day, hrfc_hour = curr_temp_response['hourly']['time'][i].split('T')
        graphics.set_font("serif")        
        graphics.set_pen(GREEN)
        graphics.set_thickness(6)
        graphics.text(hrfc_hour, 0, forecast_title_y + (forecast_offset * hci), 800, 2)
        hourly_forecast = f"{curr_temp_response['hourly']['temperature_2m'][i]}c {curr_temp_response['hourly']['precipitation_probability'][i]}%"
        graphics.set_pen(BLACK)
        graphics.set_font("sans")
        graphics.set_thickness(4)
        graphics.text(hourly_forecast, 190, forecast_title_y + (forecast_offset * hci), 800, 2)

    # Display the location name and additional weather information
    graphics.set_font("sans")        
    graphics.set_pen(RED)
    graphics.set_thickness(10)
    graphics.text(LOCATION[2], 530, 130, 800, 4, 0, 1)
    
    graphics.set_font("sans")
    graphics.set_pen(BLACK)
    graphics.set_thickness(4)
    graphics.text("H 77% UV 1.45", 545, 190, 800, 1)
    graphics.text("AQI 26 Fair", 545, 220, 800, 1)
    
    graphics.line(0, 280, 190, 280, 4) # line(x1, y1, x2, y2, thickness)
    
    # Display forecast labels
    graphics.set_font("sans")
    graphics.set_pen(BLACK)
    graphics.set_thickness(4)
    graphics.text("Low       High     Rain", 230, 280, 800, 1)
    
    # Extract daily weather forecast data
    forecast_start_y = 330
    forecast_offset_y = 60
    
    for i in range(0, 3):
        forecast_dt = curr_temp_response['daily']['time'][i]
        forecast_year, forecast_month, forecast_day = map(int, forecast_dt.split('-'))
        day_of_week = calc_dow(forecast_year, forecast_month, forecast_day)
        
        graphics.set_font("serif")
        graphics.set_pen(BLACK)
        graphics.set_thickness(6)
        debug_print("DEBUG: DOW num / day:" + str(day_of_week) + " - " + str(fDOW[day_of_week]))
        graphics.text(fDOW[day_of_week], 0, forecast_start_y + (forecast_offset_y * i), 800, 2)
        
        daily_forecast = f"{curr_temp_response['daily']['temperature_2m_min'][i]}c {curr_temp_response['daily']['temperature_2m_max'][i]}c {curr_temp_response['daily']['precipitation_probability_max'][i]}%"
        graphics.set_pen(BLUE)
        graphics.set_thickness(4)
        graphics.text(daily_forecast, 140, forecast_start_y + (forecast_offset_y * i), 800, 2, 0, 1)
        
    #Get the battery state of charge (SOC)    
    soc = get_soc()
    print(f"DEBUG SOC = {soc}")
        
    graphics.update()
    return 1

def remote_weather(REMOTE_LOCATIONS):
    """Fetch and display the weather for multiple locations."""
    headers = {
        'Content-type': 'application/json',
        'Accept': 'application/json'
    }

    debug_print("Fetching weather for multiple locations...")

    # Initialize dictionary to store weather data for each remote location
    weather_data = {}

    for location in REMOTE_LOCATIONS:
        location_info = locations.get(location)
        if not location_info:
            print(f"Location {location} not found in the locations dictionary.")
            continue

        latitude, longitude, short_name = location_info
        curr_temp_endpoint = f'https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&wind_speed_unit=mph&precipitation_unit=inch&timezone=Europe%2FLondon&forecast_days=1'

        print(f"Fetching weather for {short_name}...")
        try:
            response = requests.get(curr_temp_endpoint)
            if response.status_code == 200:
                weather_data[location] = response.json()
                debug_print(f"Weather response for {short_name}: {weather_data[location]}")
            else:
                print(f"Error: Failed to fetch weather for {short_name} (status code: {response.status_code})")
                continue
        except Exception as error:
            print(f"Error fetching weather data for {short_name}: {error}")
            continue

    # Display weather data for all remote locations
    graphics.set_font("serif")
    graphics.set_pen(BLACK)
    graphics.set_thickness(6)
    
    y_position = 453  # Starting Y position for displaying weather
    for i, location in enumerate(REMOTE_LOCATIONS):
        if location in weather_data:
            location_info = locations[location]
            short_name = location_info[2]
            min_temp = weather_data[location]['daily']['temperature_2m_min'][0]
            max_temp = weather_data[location]['daily']['temperature_2m_max'][0]
            forecast_text = f"{short_name}: {min_temp}c {max_temp}c"
            debug_print("DEBUG: Y POS = " + str(y_position))
            graphics.text(forecast_text, 0, y_position, 800, 2)
            y_position -= 75  # Move up for the next location
        else:
            debug_print("Skipping " + location + ", do not have weather data")

    soc = get_soc()
    draw_batt(soc)
    
    graphics.update()
    return 1


def get_soc():
    headers_and_token = {
        'Content-type': 'application/json',
        'Accept': 'application/json',
        'Authorization': the_bearer_token_string }
    inverter_response = requests.get(inverter_endpoint, headers=headers_and_token)
    if inverter_response.status_code == 200:
        inverter_response = inverter_response.json()
        debug_print(f"Inverter response: {inverter_response}")
    else:
        print("Error: inverter_response is None")
        
    # Ensure inverter_response['data'] exists and check for 'soc'
    soc = 0 #default to a 0 State of Charge for the battery
    if inverter_response and 'data' in inverter_response and inverter_response['data'] is not None:
        if 'soc' in inverter_response['data'] and inverter_response['data']['soc'] is not None:
            soc = round(float(inverter_response['data']['soc']))
        else:
            print("SOC is missing or None, using default value of 0")
            soc = 0  # Assign default value
    else:
        print("Inverter data is missing, using default value for SOC.")
        soc = 0
        
    return soc


def draw_batt(soc):
    """Draw battery status indicator based on state of charge."""
    graphics.set_font("sans")
    graphics.set_pen(BLACK)
    graphics.set_thickness(4)
    graphics.text('Batt', 730, 105, 800, 1)

    batt_y = 130
    batt_c = [GREEN if soc >= 80 else BLACK] * 6

    empty_sqrs = max(0, 6 - round(soc / 16.6))

    for i in range(6):
        graphics.set_pen(batt_c[i])
        graphics.rectangle(720, batt_y, 80, 50)  # draw rectangle - x,y,width, height
        if i < empty_sqrs:
            graphics.set_pen(WHITE)
            graphics.rectangle(730, batt_y, 60, 40)
        batt_y += 60

    # Display percentage and battery level indicator
    graphics.set_pen(BLACK)
    CURR_TRI_Y = 490 - round(soc * 3.5) + 10
    graphics.triangle(690, CURR_TRI_Y - 40, 690, CURR_TRI_Y, 718, CURR_TRI_Y - 20)

    text_y = CURR_TRI_Y - 60 if soc < 45 else CURR_TRI_Y + 30
    graphics.text(f"{soc}%" if soc < 100 else "Full", 585, text_y, 800, 2)


def calc_dow(year,month,day):
    """Calculate the day of the week for a given date.
    Sunday = 1, Saturday = 7
    http://en.wikipedia.org/wiki/Zeller%27s_congruence """
    m, q = month, day
    if m == 1:
        m = 13
        year -= 1
    elif m == 2:
        m = 14
        year -= 1
    K = year % 100    
    J = year // 100
    f = (q + int(13*(m + 1)/5.0) + K + int(K/4.0))
    fg = f + int(J/4.0) - 2 * J
    fj = f + 5 - J
    if year > 1582:
        dow = fg % 7
    else:
        dow = fj % 7
    if dow == 0:
        dow = 7
    return dow

def clear_screen():
    """Clear the screen."""
    graphics.set_pen(WHITE)
    graphics.clear()


def update_clock_ntp():
    """Update RTC with time from NTP server."""
    uasyncio.get_event_loop().run_until_complete(network_manager.client(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK))
    rtc = RTC()
    print('Attempting NTP update...')
    try:
        ntptime.settime()
        print("NTP sync successful")
    except OSError as error:
        print(f"Error updating time from NTP: {error}")
    timestamp = rtc.datetime()
    print(f"UTC Time: {timestamp}")


def update():
    """Main update loop."""
    while True:
        clear_screen()
        update_clock_ntp()
        my_bearer_token()
        my_current_usage()

        gc.collect()
        time.sleep(UPDATE_INTERVAL)

        clear_screen()
        update_clock_ntp()
        my_current_weather(locations['Local'])

        gc.collect()
        time.sleep(UPDATE_INTERVAL)

        clear_screen()
        update_clock_ntp()
        remote_weather(locations['ListOrder'])

        gc.collect()
        time.sleep(UPDATE_INTERVAL)


# Run the update loop if executed as a script
if __name__ == "__main__":
    update()
