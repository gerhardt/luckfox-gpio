#!/usr/bin/env python3
"""
GPIO Web Control Server with SCPI Interface for LuckFox Pico Max
Provides both web interface and SCPI command interface for GPIO control
nicely branded with the light & matter group logo
(copyleft, 2025) - Ilja Gerhardt
https://www.fkp.uni-hannover.de/en/research-groups/translate-to-english-light-matter-ilja-gerhardt
"""

from flask import Flask, render_template, request, jsonify, current_app
from periphery import GPIO
import os
import sys
import time
import threading
import logging
import socket
import select
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP
IP_ADDRESS=get_ip()
MAC_ADDRESS=open('/sys/class/net/eth0/address').readline()

# GPIO Configuration
AVAILABLE_PINS = {
    54: "GPIO1_C6",
    55: "GPIO1_C7", 
    # Add more pins as needed - refer to LuckFox pinout diagram
    # Pin calculation: bank * 32 + (group * 8 + X)
    # Example: GPIO1_C7 = 1 * 32 + (2 * 8 + 7) = 55
}

# Active GPIO instances
active_gpios = {}

# SCPI Server Configuration
SCPI_PORT = 5025
SCPI_MAX_CLIENTS = 5
scpi_server_running = False

def cleanup_gpios():
    """Clean up all active GPIO instances"""
    for pin_num, gpio_obj in active_gpios.items():
        try:
            gpio_obj.close()
            logging.info(f"Cleaned up GPIO {pin_num}")
        except Exception as e:
            logging.error(f"Error cleaning up GPIO {pin_num}: {e}")
    active_gpios.clear()

def setup_gpio(pin_num, direction="out"):
    """Setup a GPIO pin"""
    try:
        if pin_num in active_gpios:
            active_gpios[pin_num].close()
        
        gpio_obj = GPIO(pin_num, direction)
        active_gpios[pin_num] = gpio_obj
        return True
    except Exception as e:
        logging.error(f"Error setting up GPIO {pin_num}: {e}")
        return False

# SCPI Command Handler
class SCPICommandHandler:
    def __init__(self):
        self.commands = {
            '*IDN?': self.identify,
            '*RST': self.reset,
            'SYST:ERR?': self.get_error,
            'GPIO:LIST?': self.list_gpios,
            'GPIO:SETUP': self.setup_gpio_scpi,
            'GPIO:WRITE': self.write_gpio_scpi,
            'GPIO:READ?': self.read_gpio_scpi,
            'GPIO:TOGGLE': self.toggle_gpio_scpi,
            'GPIO:STATUS?': self.get_gpio_status,
        }
        self.last_error = "0,\"No error\""
    
    def identify(self, params=None):
        """*IDN? - Identification query"""
        return "LuckFox,GPIO-Controller,v1.0,2025"
    
    def reset(self, params=None):
        """*RST - Reset all GPIOs"""
        try:
            cleanup_gpios()
            self.last_error = "0,\"No error\""
            return "OK"
        except Exception as e:
            self.last_error = f"1,\"Reset error: {str(e)}\""
            return "ERROR"
    
    def get_error(self, params=None):
        """SYST:ERR? - Get last error"""
        error = self.last_error
        self.last_error = "0,\"No error\""
        return error
    
    def list_gpios(self, params=None):
        """GPIO:LIST? - List available GPIO pins"""
        pins = ','.join([f"{pin}({name})" for pin, name in AVAILABLE_PINS.items()])
        return pins
    
    def setup_gpio_scpi(self, params):
        """GPIO:SETUP <pin>,<direction> - Setup GPIO pin"""
        try:
            if not params or len(params.split(',')) != 2:
                self.last_error = "2,\"Invalid parameters. Use: GPIO:SETUP <pin>,<direction>\""
                return "ERROR"
            
            pin_str, direction = params.split(',')
            pin = int(pin_str.strip())
            direction = direction.strip().lower()
            
            if pin not in AVAILABLE_PINS:
                self.last_error = f"3,\"Invalid pin {pin}\""
                return "ERROR"
            
            if direction not in ['in', 'out']:
                self.last_error = "4,\"Direction must be 'in' or 'out'\""
                return "ERROR"
            
            success = setup_gpio(pin, direction)
            if success:
                self.last_error = "0,\"No error\""
                return "OK"
            else:
                self.last_error = f"5,\"Failed to setup GPIO {pin}\""
                return "ERROR"
                
        except ValueError:
            self.last_error = "6,\"Invalid pin number\""
            return "ERROR"
        except Exception as e:
            self.last_error = f"7,\"Setup error: {str(e)}\""
            return "ERROR"
    
    def write_gpio_scpi(self, params):
        """GPIO:WRITE <pin>,<value> - Write to GPIO pin"""
        try:
            if not params or len(params.split(',')) != 2:
                self.last_error = "2,\"Invalid parameters. Use: GPIO:WRITE <pin>,<value>\""
                return "ERROR"
            
            pin_str, value_str = params.split(',')
            pin = int(pin_str.strip())
            value_str = value_str.strip().upper()
            
            if pin not in AVAILABLE_PINS:
                self.last_error = f"3,\"Invalid pin {pin}\""
                return "ERROR"
            
            if pin not in active_gpios:
                self.last_error = f"8,\"GPIO {pin} not initialized\""
                return "ERROR"
            
            # Parse value (accept 0/1, ON/OFF, HIGH/LOW, TRUE/FALSE)
            if value_str in ['1', 'ON', 'HIGH', 'TRUE']:
                value = True
            elif value_str in ['0', 'OFF', 'LOW', 'FALSE']:
                value = False
            else:
                self.last_error = "9,\"Invalid value. Use: 0/1, ON/OFF, HIGH/LOW, TRUE/FALSE\""
                return "ERROR"
            
            active_gpios[pin].write(value)
            self.last_error = "0,\"No error\""
            return "OK"
            
        except ValueError:
            self.last_error = "6,\"Invalid pin number\""
            return "ERROR"
        except Exception as e:
            self.last_error = f"10,\"Write error: {str(e)}\""
            return "ERROR"
    
    def read_gpio_scpi(self, params):
        """GPIO:READ? <pin> - Read GPIO pin value"""
        try:
            if not params:
                self.last_error = "2,\"Invalid parameters. Use: GPIO:READ? <pin>\""
                return "ERROR"
            
            pin = int(params.strip())
            
            if pin not in AVAILABLE_PINS:
                self.last_error = f"3,\"Invalid pin {pin}\""
                return "ERROR"
            
            if pin not in active_gpios:
                self.last_error = f"8,\"GPIO {pin} not initialized\""
                return "ERROR"
            
            value = active_gpios[pin].read()
            self.last_error = "0,\"No error\""
            return "1" if value else "0"
            
        except ValueError:
            self.last_error = "6,\"Invalid pin number\""
            return "ERROR"
        except Exception as e:
            self.last_error = f"11,\"Read error: {str(e)}\""
            return "ERROR"
    
    def toggle_gpio_scpi(self, params):
        """GPIO:TOGGLE <pin> - Toggle GPIO pin"""
        try:
            if not params:
                self.last_error = "2,\"Invalid parameters. Use: GPIO:TOGGLE <pin>\""
                return "ERROR"
            
            pin = int(params.strip())
            
            if pin not in AVAILABLE_PINS:
                self.last_error = f"3,\"Invalid pin {pin}\""
                return "ERROR"
            
            if pin not in active_gpios:
                self.last_error = f"8,\"GPIO {pin} not initialized\""
                return "ERROR"
            
            current_value = active_gpios[pin].read()
            new_value = not current_value
            active_gpios[pin].write(new_value)
            self.last_error = "0,\"No error\""
            return "1" if new_value else "0"
            
        except ValueError:
            self.last_error = "6,\"Invalid pin number\""
            return "ERROR"
        except Exception as e:
            self.last_error = f"12,\"Toggle error: {str(e)}\""
            return "ERROR"
    
    def get_gpio_status(self, params=None):
        """GPIO:STATUS? - Get status of all active GPIOs"""
        try:
            status_list = []
            for pin_num, gpio_obj in active_gpios.items():
                try:
                    value = gpio_obj.read()
                    status_list.append(f"{pin_num}:{value}")
                except Exception:
                    status_list.append(f"{pin_num}:ERROR")
            
            if not status_list:
                return "NO_ACTIVE_GPIOS"
            
            self.last_error = "0,\"No error\""
            return ','.join(status_list)
            
        except Exception as e:
            self.last_error = f"13,\"Status error: {str(e)}\""
            return "ERROR"
    
    def process_command(self, command):
        """Process an SCPI command"""
        command = command.strip()
        if not command:
            return "ERROR"
        
        # Split command and parameters
        if ' ' in command:
            cmd, params = command.split(' ', 1)
        else:
            cmd, params = command, None
        
        cmd = cmd.upper()
        
        # Handle query commands (ending with ?)
        if cmd in self.commands:
            try:
                return self.commands[cmd](params)
            except Exception as e:
                self.last_error = f"99,\"Command error: {str(e)}\""
                return "ERROR"
        else:
            self.last_error = f"100,\"Unknown command: {cmd}\""
            return "ERROR"

def handle_scpi_client(client_socket, client_address):
    """Handle individual SCPI client connection"""
    handler = SCPICommandHandler()
    logging.info(f"SCPI client connected from {client_address}")
    
    try:
        # Send welcome message
        welcome = f"# LuckFox GPIO SCPI Server Ready - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        client_socket.send(welcome.encode('utf-8'))
        
        buffer = ""
        while True:
            # Set timeout for client socket
            client_socket.settimeout(60.0)  # 60 second timeout
            
            try:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                
                # Process complete commands (terminated by \n or \r\n)
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.rstrip('\r')
                    
                    if line.strip():
                        logging.info(f"SCPI command from {client_address}: {line}")
                        response = handler.process_command(line)
                        client_socket.send(f"{response}\n".encode('utf-8'))
                        
            except socket.timeout:
                logging.info(f"SCPI client {client_address} timed out")
                break
            except Exception as e:
                logging.error(f"Error handling SCPI client {client_address}: {e}")
                break
                
    except Exception as e:
        logging.error(f"SCPI client handler error: {e}")
    finally:
        client_socket.close()
        logging.info(f"SCPI client {client_address} disconnected")

def scpi_server():
    """SCPI server main loop"""
    global scpi_server_running
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind(('0.0.0.0', SCPI_PORT))
        server_socket.listen(SCPI_MAX_CLIENTS)
        scpi_server_running = True
        
        logging.info(f"SCPI server listening on port {SCPI_PORT}")
        
        while scpi_server_running:
            try:
                server_socket.settimeout(1.0)  # Non-blocking accept with timeout
                client_socket, client_address = server_socket.accept()
                
                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=handle_scpi_client,
                    args=(client_socket, client_address),
                    daemon=True
                )
                client_thread.start()
                
            except socket.timeout:
                continue  # Check if server should still be running
            except Exception as e:
                if scpi_server_running:
                    logging.error(f"SCPI server error: {e}")
                break
                
    except Exception as e:
        logging.error(f"Failed to start SCPI server: {e}")
    finally:
        server_socket.close()
        scpi_server_running = False
        logging.info("SCPI server stopped")

# Flask Web Interface Routes
@app.route('/')
def index():
    """Main web interface"""
    return render_template('index.html', pins=AVAILABLE_PINS, ipa=IP_ADDRESS, mac=MAC_ADDRESS)

@app.route('/help')
def help():
    """HELP interface"""
    return render_template('help.html', pins=AVAILABLE_PINS, ipa=IP_ADDRESS, mac=MAC_ADDRESS)

@app.route('/pinout')
def pinout():
    """Image interface"""
    return current_app.send_static_file("luckfox_pinout.jpg")

@app.route('/favicon.ico')
def favicon():
    """Favicon interface"""
    return current_app.send_static_file("favicon.ico")

@app.route('/css')
def css():
    """CSS interface"""
    return current_app.send_static_file("styles.css")

@app.route('/api/gpio/<int:pin>/setup', methods=['POST'])
def setup_pin(pin):
    """Setup a GPIO pin"""
    if pin not in AVAILABLE_PINS:
        return jsonify({"error": "Invalid pin number"}), 400
    
    direction = request.json.get('direction', 'out')
    if direction not in ['in', 'out']:
        return jsonify({"error": "Direction must be 'in' or 'out'"}), 400
    
    success = setup_gpio(pin, direction)
    if success:
        return jsonify({"status": "success", "message": f"GPIO {pin} setup as {direction}"})
    else:
        return jsonify({"error": "Failed to setup GPIO"}), 500

@app.route('/api/gpio/<int:pin>/write', methods=['POST'])
def write_pin(pin):
    """Write to a GPIO pin"""
    if pin not in AVAILABLE_PINS:
        return jsonify({"error": "Invalid pin number"}), 400
    
    if pin not in active_gpios:
        return jsonify({"error": "GPIO not initialized. Setup pin first."}), 400
    
    try:
        value = request.json.get('value')
        if value not in [0, 1, True, False]:
            return jsonify({"error": "Value must be 0, 1, True, or False"}), 400
        
        active_gpios[pin].write(bool(value))
        return jsonify({"status": "success", "message": f"GPIO {pin} set to {value}"})
    
    except Exception as e:
        return jsonify({"error": f"Failed to write GPIO: {str(e)}"}), 500

@app.route('/api/gpio/<int:pin>/read', methods=['GET'])
def read_pin(pin):
    """Read from a GPIO pin"""
    if pin not in AVAILABLE_PINS:
        return jsonify({"error": "Invalid pin number"}), 400
    
    if pin not in active_gpios:
        return jsonify({"error": "GPIO not initialized. Setup pin first."}), 400
    
    try:
        value = active_gpios[pin].read()
        return jsonify({"status": "success", "value": value})
    
    except Exception as e:
        return jsonify({"error": f"Failed to read GPIO: {str(e)}"}), 500

@app.route('/api/gpio/<int:pin>/toggle', methods=['POST'])
def toggle_pin(pin):
    """Toggle a GPIO pin"""
    if pin not in AVAILABLE_PINS:
        return jsonify({"error": "Invalid pin number"}), 400
    
    if pin not in active_gpios:
        return jsonify({"error": "GPIO not initialized. Setup pin first."}), 400
    
    try:
        current_value = active_gpios[pin].read()
        new_value = not current_value
        active_gpios[pin].write(new_value)
        return jsonify({"status": "success", "message": f"GPIO {pin} toggled to {new_value}"})
    
    except Exception as e:
        return jsonify({"error": f"Failed to toggle GPIO: {str(e)}"}), 500

@app.route('/api/gpio/status', methods=['GET'])
def gpio_status():
    """Get status of all active GPIOs"""
    status = {}
    for pin_num, gpio_obj in active_gpios.items():
        try:
            value = gpio_obj.read()
            status[pin_num] = {
                "name": AVAILABLE_PINS[pin_num],
                "value": value,
                "active": True
            }
        except Exception as e:
            status[pin_num] = {
                "name": AVAILABLE_PINS[pin_num],
                "error": str(e),
                "active": False
            }
    
    return jsonify(status)

# Create templates directory and file
import tempfile
import atexit

templates_dir = "templates"

# Cleanup on exit
def cleanup_all():
    global scpi_server_running
    scpi_server_running = False
    cleanup_gpios()

atexit.register(cleanup_all)

if __name__ == '__main__':
    # Check if running as root (required for GPIO access)
    if os.geteuid() != 0:
        print("Warning: This script should be run as root for GPIO access")
        print("Use: sudo python3 gpio_server.py")
    
    try:
        print("Starting GPIO Web Server with SCPI Interface...")
        print("Web interface: http://your-luckfox-ip")
        print("SCPI interface: telnet your-luckfox-ip 5025")
        print("Press Ctrl+C to stop")
        
        # Start SCPI server in separate thread
        scpi_thread = threading.Thread(target=scpi_server, daemon=True)
        scpi_thread.start()
        
        for pin, name in AVAILABLE_PINS.items():
            setup_gpio(pin,'out')
        # Start Flask web server
        app.run(host='0.0.0.0', port=80, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        cleanup_all()
    except Exception as e:
        print(f"Error: {e}")
        cleanup_all()
