from network_manager import NetworkManager
import uasyncio
import WIFI_CONFIG
import sys
import json
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_7 as DISPLAY
#Inky Frame 7 is 7.3" (800 x 480)
graphics = PicoGraphics(DISPLAY)
import gc
from machine import Pin
from pimoroni_i2c import PimoroniI2C
from pcf85063a import PCF85063A
import time
import machine
import ntptime
from machine import RTC
import requests
import inky_helper as ih

I2C_SDA_PIN = 4
I2C_SCL_PIN = 5
HOLD_VSYS_EN_PIN = 2

# Turn any LEDs off that may still be on from last run.
ih.clear_button_leds()
ih.led_warn.off()

# intialise the pcf85063a real time clock chip
i2c = PimoroniI2C(I2C_SDA_PIN, I2C_SCL_PIN, 100000)
rtc = PCF85063A(i2c)

# set up and enable vsys hold so we don't go to sleep
hold_vsys_en_pin = Pin(HOLD_VSYS_EN_PIN, Pin.OUT)
hold_vsys_en_pin.value(True)

# Length of time between updates in Seconds.
# Frequent updates will reduce battery life!
UPDATE_INTERVAL = 60 * 1

def status_handler(mode, status, ip):
    print(mode, status, ip)

network_manager = NetworkManager(WIFI_CONFIG.COUNTRY, status_handler=status_handler)

BLACK = 0
WHITE = 1
GREEN = 2
BLUE = 3
RED = 4
YELLOW = 5
ORANGE = 6
TAUPE = 7

DOW = ['Mon', 'Tue', 'Wed', 'Thr', 'Fri', 'Sat', 'Sun']
fDOW = ['DOW', 'Sun', 'Mon', 'Tue', 'Wed', 'Thr', 'Fri', 'Sat']

locations = {}

#Get location data
if ih.file_exists("locations.json"):
    locations_json = json.loads(open("/locations.json", "r").read())
    if type(locations_json) is dict:
        locations = locations_json
else:
    with open("/locations.json", "w") as f:
        #set the local location by default to be London
        locations['Local'] = ['51.507351', '-0.127758', 'LON']
        locations['New York'] = ['40.712776', '-74.005974', 'NYC']
        locations['Singapore'] = ['1.352083', '103.819839', 'SGP']
        locations['Manchester'] = ['53.480759', '-2.242631', 'MAN']
        locations['Malmo'] = ['55.604980', '13.003822', 'MMX']
        locations['ListOrder'] = ['Manchester', 'Singapore', 'Malmo', 'New York', 'Local']
        f.write(json.dumps(locations))
        f.flush()

#print ("Debug locations:" + str(locations))
LOCAL_LOCATION = locations['Local']

# URL background
# Your login details are redirected to the authentication URL, which provides your bearer token for future API requests
# 
# https://sunsynk.net/ 
# This is your Login landing page once you have created your account with SynSynk
# Enter your username and password that you created on the Sunsynk website.
my_user_email=""
my_user_password=""
my_sun_serial=""
try:
    from secrets import SUN_EMAIL, SUN_PW, SUN_SERIAL
    my_user_email=SUN_EMAIL
    my_user_password=SUN_PW
    my_sun_serial=SUN_SERIAL
except ImportError:
    print("Create secrets.py with your SunSync credentials")
    quit()

loginurl = ('https://api.sunsynk.net/oauth/token')

# API call to get realtime inverter related information
plant_id_endpoint = 'https://api.sunsynk.net/api/v1/plants?page=1&limit=10&name=&status='
inverter_endpoint = 'https://api.sunsynk.net/api/v1/inverter/battery/%s/realtime?sn=%s&lan=en'%(my_sun_serial,my_sun_serial)
grid_endpoint = 'https://api.sunsynk.net/api/v1/inverter/grid/%s/realtime?sn=%s&lan=en'%(my_sun_serial,my_sun_serial)
load_endpoint = 'https://api.sunsynk.net/api/v1/inverter/load/%s/realtime?sn=%s&lan=en'%(my_sun_serial,my_sun_serial)

def print_header(local_curr_time, local_curr_temp):
    rtc_current=machine.RTC()
    timestamp=rtc_current.datetime()
    dow_now = DOW[timestamp[3]]
    timestring1="%02d-%02d"%(timestamp[1:3])
    if (int(timestamp[4]) + 1) == 24:
        timestring2='00'
    else:
        timestring2=str(int(timestamp[4]) + 1)
    #timestring2=str(timestamp[4])    
    timestring="%s %s %s:%s"%(dow_now, timestring1, timestring2, timestamp[5])
    print (timestring + ' - Now') #current time
    print (local_curr_time + ' - Weather Data') #timestamp of weather data

    graphics.set_pen(BLACK)
    graphics.rectangle(0, 0, 800, 60)
    graphics.set_font("sans")
    graphics.set_pen(WHITE)
    graphics.set_thickness(4)
    graphics.text(timestring, 15, 35, 800, 2)

    graphics.set_pen(YELLOW)
    graphics.text(str(local_curr_temp) + 'c', 590, 35, 800, 2)
    
    graphics.set_pen(BLACK)
    return 1

# This function will print your bearer/access token
def my_bearer_token():
    # Connect to WiFi
    uasyncio.get_event_loop().run_until_complete(network_manager.client(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK))
    headers = {
    'Content-type':'application/json', 
    'Accept':'application/json'
    }

    payload = {
        "username": my_user_email,
        "password": my_user_password,
        "grant_type":"password",
        "client_id":"csp-web"
        }

    try:
        raw_data = requests.post(loginurl, json=payload, headers=headers).json()
    except OSError as error:
        print(str("errornr="),error)
    # Your access token extracted from response
    my_access_token = raw_data["data"]["access_token"]
    global the_bearer_token_string
    the_bearer_token_string = ('Bearer '+ my_access_token)
    print('****************************************************')
    print('Your access token is: ' + my_access_token)
    return my_access_token

# Get plant id and current generation in Watts
def my_current_usage():
    headers_and_token = {
    'Content-type':'application/json', 
    'Accept':'application/json',
    'Authorization': the_bearer_token_string
    }
    r = requests.get(plant_id_endpoint, headers=headers_and_token)
    data_response = r.json()
    inverter_req = requests.get(inverter_endpoint, headers=headers_and_token)
    inverter_response = inverter_req.json()
    grid_req = requests.get(grid_endpoint, headers=headers_and_token)
    grid_response = grid_req.json()
    load_req = requests.get(load_endpoint, headers=headers_and_token)
    load_response = load_req.json()
    local_curr_temp_endpoint = 'https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s'%(LOCAL_LOCATION[0], LOCAL_LOCATION[1])
    local_curr_temp_endpoint = local_curr_temp_endpoint + '&current=temperature_2m&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&wind_speed_unit=mph&precipitation_unit=inch&timezone=Europe%2FLondon&forecast_days=5'
    curr_temp_req = requests.get(local_curr_temp_endpoint)
    curr_temp_response = curr_temp_req.json()
    gc.collect()
    #print('****************************************************')
    plant_id_and_pac = data_response['data']['infos']
    for d in plant_id_and_pac:
        your_plant_id = d['id']
        your_plant_pac = d['pac']
        #print(str(d))
        current_gen_w = int(your_plant_pac)
        #print('Your plant id is: ' + str(your_plant_id))
        #print('****************************************************')
        # You can take actions based on the generation amount, e.g. trigger IoT device, SMS, adjust inverter settings like push to grid
        #print('Your current power generation is: ' + str(current_gen_w) +'W')
        #print('****************************************************')
        print('id:'+str(your_plant_id)+':cur:'+str(your_plant_pac) + 'W'
+ ':update:'+ str(d['updateAt'])+':')
        #print(str(inverter_response['data']))
        your_soc = round(float(inverter_response['data']['soc']))
        your_bat_usg = int(inverter_response['data']['power'])
        your_grid = int(grid_response['data']['vip'][0]['power'])
        your_load = int(load_response['data']['vip'][0]['power'])
        local_curr_temp = curr_temp_response['current']['temperature_2m']
        local_curr_time = curr_temp_response['current']['time']
        
        print_header(local_curr_time, local_curr_temp)
        
        graphics.set_font("serif")        
        graphics.set_pen(BLACK)
        graphics.set_thickness(6)
        #best - 60, 150, 255, 358, 460
        pv_titles_y = 153
        pv_titles = ['Genr:', 'Load:', 'BatU:', 'Grid:']
        pv_titles = ['Pv:', 'Ld:', 'Bt:', 'Gr:']
        for i in range (0, 4):
            graphics.text(pv_titles[i], 0, pv_titles_y, 800, 2)
            pv_titles_y = pv_titles_y + (i+1*100)
        
        graphics.set_font("sans")
        graphics.set_thickness(8)
        
        
        #50, 132, 232, 336, 440
        #GENERATED ELEC
        if (current_gen_w < 100):
            graphics.set_pen(RED)
        else:
            graphics.set_pen(GREEN)
        graphics.text(str(current_gen_w) + 'w', 110, 132, 800, 4)

        #ELEC LOAD
        graphics.set_pen(BLACK)
        graphics.text(str(your_load) + 'w', 110, 232, 800, 4)
        
        #BATT USAGE
        if (your_bat_usg > 1):
            graphics.set_pen(RED)
            graphics.text(str(your_bat_usg) + 'w+', 110, 336, 800, 4)
        else:
            graphics.set_pen(GREEN)
            graphics.text(str(your_bat_usg)[1:] + 'w-', 110, 336, 800, 4)

        #ELEC GRID
        graphics.set_pen(BLACK)
        if (your_grid < 0):
            graphics.set_pen(RED)
            graphics.text(str(your_grid)[1:] + 'w-', 110, 440, 800, 4)
        else:
            graphics.set_pen(BLUE)
            graphics.text(str(your_grid) + 'w', 110, 440, 800, 4)
        
        draw_batt(your_soc)
        
        graphics.update()
    return current_gen_w

def my_current_weather(LOCATION):
    # Connect to WiFi
    uasyncio.get_event_loop().run_until_complete(network_manager.client(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK))
    headers = {
    'Content-type':'application/json', 
    'Accept':'application/json'
    }
    
    curr_temp_endpoint = 'https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s'%(LOCATION[0], LOCATION[1])
    curr_temp_endpoint = curr_temp_endpoint + '&current=temperature_2m&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&wind_speed_unit=mph&precipitation_unit=inch&timezone=Europe%2FLondon&forecast_days=5'

    print ('WEATHER RUN: ' + LOCATION[2])
    try:
        curr_temp_req = requests.get(curr_temp_endpoint)
    except OSError as error:
        print(str("errornr="),error)
    curr_temp_response = curr_temp_req.json()
    gc.collect()
    local_curr_temp = curr_temp_response['current']['temperature_2m']
    local_curr_time = curr_temp_response['current']['time']
    print_header(local_curr_time, local_curr_temp)
    
    
    ft_start_y = 50
    ft_offset = 60
    
    hci = 0
    
    rtc_current=machine.RTC()
    timestamp=rtc_current.datetime()
    firsthr = int(timestamp[4]) + 1
    lasthr = firsthr + 3
    
    
    for i in range (firsthr, lasthr):
        hci = hci + 1
        graphics.set_font("serif")        
        graphics.set_pen(GREEN)
        graphics.set_thickness(6)
        hrfc_day, hrfc_hour = curr_temp_response['hourly']['time'][i].split('T')
        graphics.text(hrfc_hour, 0, ft_start_y + (ft_offset * hci), 800, 2)
        day_forecast = "%sc %s"%(curr_temp_response['hourly']['temperature_2m'][i],
                            curr_temp_response['hourly']['precipitation_probability'][i])
        day_forecast = day_forecast + '%'
        graphics.set_pen(BLACK)
        graphics.set_font("sans")
        graphics.set_thickness(4)
        graphics.text(day_forecast, 190, ft_start_y + (ft_offset * hci), 800, 2)
    
    graphics.set_font("sans")        
    graphics.set_pen(RED)
    graphics.set_thickness(10)
    graphics.text(LOCATION[2], 530, 130, 800, 4, 0, 1)
    
    graphics.set_font("sans")
    graphics.set_pen(BLACK)
    graphics.set_thickness(4)
    graphics.text("H 77% UV 1.45", 545, 190, 800, 1)
    graphics.text("AQI 26 Fair", 545, 220, 800, 1)
    
    graphics.line(0, 280, 190, 280, 4) #line(x1, y1, x2, y2, thickness)
    
    graphics.set_font("sans")
    graphics.set_pen(BLACK)
    graphics.set_thickness(4)
    graphics.text("Low       High     Rain", 230, 280, 800, 1)
    
    ft_start_y = 330
    ft_offset = 60
    
    for i in range (0, 3):
        forecast_dt = curr_temp_response['daily']['time'][i]
        forecast_year, forecast_month, forecase_day = (int(x) for x in forecast_dt.split('-'))
        ans = calc_dow(forecast_year, forecast_month, forecase_day)
        graphics.set_font("serif")        
        graphics.set_pen(BLACK)
        graphics.set_thickness(6)
        graphics.text(fDOW[int(ans)], 0, ft_start_y + (ft_offset * i), 800, 2)
        day_forecast = "%sc %sc %s"%(curr_temp_response['daily']['temperature_2m_min'][i],
                            curr_temp_response['daily']['temperature_2m_max'][i],
                            curr_temp_response['daily']['precipitation_probability_max'][i])
        day_forecast = day_forecast + '%'
        graphics.set_font("sans")
        graphics.set_pen(BLUE)
        graphics.set_thickness(4)
        graphics.text(day_forecast, 140, ft_start_y + (ft_offset * i), 800, 2, 0, 1)
        #print (i)
    
    graphics.update()
    
    return 1

def remote_weather(REMOTE_LOCATIONS):
    # Connect to WiFi
    uasyncio.get_event_loop().run_until_complete(network_manager.client(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK))
    
    headers_and_token = {
    'Content-type':'application/json', 
    'Accept':'application/json',
    'Authorization': the_bearer_token_string
    }
    inverter_req = requests.get(inverter_endpoint, headers=headers_and_token)
    inverter_response = inverter_req.json()
    your_soc = round(float(inverter_response['data']['soc']))
    #print ("Debug yoursoc: " + str(your_soc))
    draw_batt(your_soc)
    
    
    headers = {
    'Content-type':'application/json', 
    'Accept':'application/json'
    }
    
    wloc_dict = {}
    
    for WLOC in REMOTE_LOCATIONS:
        print ('REMOTE WEATHER RUN: ' + locations[WLOC][2])
                
        wloc_temp_endpoint = 'https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s'%(locations[WLOC][0], locations[WLOC][1])
        wloc_temp_endpoint = wloc_temp_endpoint + '&current=temperature_2m&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&wind_speed_unit=mph&precipitation_unit=inch&timezone=Europe%2FLondon&forecast_days=5'
        try:
            wloc_temp_req = requests.get(wloc_temp_endpoint)
        except OSError as error:
            print(str("errornr="),error)
        wloc_temp_response = wloc_temp_req.json()
        wloc_dict[WLOC] = {'title': locations[WLOC][2], 'min': wloc_temp_response['daily']['temperature_2m_min'][0],
                           'max': wloc_temp_response['daily']['temperature_2m_max'][0]}
        
        
    #print ("Debug wloc_dict: " + str(wloc_dict))
    gc.collect()
    graphics.set_font("serif")        
    graphics.set_pen(BLACK)
    graphics.set_thickness(6)
    #best - 60, 150, 255, 358, 460
    wloc_titles_y = 453
    for i in range (0, 5):
        graphics.text(wloc_dict[REMOTE_LOCATIONS[i]]['title'] + ": " + str(wloc_dict[REMOTE_LOCATIONS[i]]['min']) + " " + str(wloc_dict[REMOTE_LOCATIONS[i]]['max']), 0, wloc_titles_y, 800, 2)
        wloc_titles_y = wloc_titles_y - (i+1*75)
        
    graphics.update()
    return 1


def calc_dow(year,month,day):
    """ day of week, Sunday = 1, Saturday = 7
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
        h = fg % 7
    else:
        h = fj % 7
    if h == 0:
        h = 7
    return h


def clear_screen():
    graphics.set_pen(WHITE)
    graphics.clear()
    return 1

def update_clock_ntp():
    #Time / Date
    uasyncio.get_event_loop().run_until_complete(network_manager.client(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK))
    #try:
    #    print('attempt to update clock via ntp')
    #    ntptime.settime()
    #except OSError:
    #    print("Unable to contact NTP server")
    #rtc_current=machine.RTC()
    #timestamp=rtc_current.datetime()
    
    rtc = RTC()
    print('attempt to update via NTP')
    try:
        ntptime.settime()
    except OSError as error:
        print(str("errornr="),error)
    print("NTP ok")
    (year, month, day, weekday, hours, minutes, seconds, subseconds) = rtc.datetime()
    print ("UTC Time: ")
    print((year, month, day, hours, minutes, seconds))
    #UTC_OFFSET = +1 * 60 * 60   # change the '-4' according to your timezone
    #timestamp = time.localtime(time.time() + UTC_OFFSET)
    rtc_current=machine.RTC()
    timestamp=rtc_current.datetime()
    timestring="%04d-%02d-%02d %02d:%02d:%02d"%(timestamp[0:3] + timestamp[4:7])
    print (timestring + ' Loop Start (UTC)')
    return 1

def draw_batt(your_soc):
    graphics.set_font("sans")
    graphics.set_pen(BLACK)
    graphics.set_thickness(4)
    graphics.text('Batt', 730, 105, 800, 1)
        
    batt_y = 130
    batt_c = [0,0,0,0,0,0] #default to black battery indicator
    if your_soc >= 80:
        batt_c = [GREEN, GREEN, GREEN, GREEN, GREEN, GREEN]

    empty_sqrs = 0
        
    if your_soc >= 16.6:
        #print ("Debug SOC: " + str(your_soc))
        full_sqrs = round(your_soc / 16.6)
        #print ("Debug SRQS: " + str(test_sqrs))
        empty_sqrs = 6 - full_sqrs
        #print ("Debug E-SRQS: " + str(empty_sqrs))
        
    for i in range (0, 6):
        graphics.set_pen(batt_c[i])
        graphics.rectangle(720, batt_y, 80, 50) # draw rectangle - x,y,width, height
        if i+1 <= empty_sqrs:
            graphics.set_pen(WHITE)
            graphics.rectangle(730, batt_y, 60, 40)
        batt_y = batt_y + 60
        
    #your_soc = 20
    graphics.set_pen(BLACK)
    MIN_TRI_Y = 490
    CURR_TRI_Y_OFFSET = round(your_soc * 3.5)
    CURR_TRI_Y = MIN_TRI_Y - CURR_TRI_Y_OFFSET + 10
    graphics.triangle(690, CURR_TRI_Y - 40, 690, CURR_TRI_Y, 718, CURR_TRI_Y - 20)#triangle(x1, y1, x2, y2, x3, y3)
    if your_soc == 100:
        graphics.text('Full', 585, CURR_TRI_Y + 30, 800, 2)
    elif your_soc >= 45:
        graphics.text(str(your_soc) + '%', 585, CURR_TRI_Y + 30, 800, 2)
    else:
        graphics.text(str(your_soc) + '%', 585, CURR_TRI_Y - 60, 800, 2)
    return 1


#update function if called from main
def update():
    while True:
        clear_screen()
        update_clock_ntp()
        #Display PV Data
        #print ('update clock done')
        my_bearer_token()
        my_current_usage()
        # Time to have a little nap until the next update
        rtc.set_timer(UPDATE_INTERVAL)
        hold_vsys_en_pin.init(Pin.IN)
        time.sleep(UPDATE_INTERVAL)
        #
        clear_screen()
        update_clock_ntp()
        my_current_weather(locations['Local'])
        # Time to have a little nap until the next update
        rtc.set_timer(UPDATE_INTERVAL)
        hold_vsys_en_pin.init(Pin.IN)
        time.sleep(UPDATE_INTERVAL)
        #
        clear_screen()
        update_clock_ntp()
        remote_weather(locations['ListOrder'])
        # Time to have a little nap until the next update
        rtc.set_timer(UPDATE_INTERVAL)
        hold_vsys_en_pin.init(Pin.IN)
        time.sleep(UPDATE_INTERVAL)


# print functions showing token and current generation in Watts
if __name__ == "__main__":
    #update()
    clear_screen()
    update_clock_ntp()
    my_bearer_token()
    remote_weather(locations['ListOrder'])
    clear_screen()
    my_current_weather(locations['New York'])
    ih.clear_button_leds()
    ih.inky_frame.button_a.led_on()
    clear_screen()
    my_current_weather(locations['Local'])
    ih.clear_button_leds()
    ih.inky_frame.button_b.led_on()
    #clear_screen()
    #ih.clear_button_leds()
    

