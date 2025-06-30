import os
import re
import sys
import ssl
import time
import json
import traceback
import threading
import subprocess
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer


OPTIONS = {
    "check_interval": 300
}


class MonkeyACLServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, firewall):
        super().__init__(server_address, RequestHandlerClass)
        self.firewall = firewall


class MonkeyACLHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def do_POST(self):
        if not self.path.startswith(f"/{OPTIONS['url']}"):
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Rejected api Call: Illegal URI address： [{self.path}] ")
            self.send_response_only(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'')
            return

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        json_data = json.loads(post_data)
        if 'auth' not in json_data.keys():
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Rejected api Call: Illegal user auth: [{None}], set auth: [{OPTIONS['auth']}]")
            return b''
        auth = json_data['auth']
        if auth != OPTIONS['auth']:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Rejected api Call: Illegal user auth: [{auth}], set auth: [{OPTIONS['auth']}]")
            self.send_response_only(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write("auth failed\n\n".encode("utf-8"))
            return

        if 'port' not in json_data.keys():
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Rejected api Call: Invalid parameter of port")
            return b''
        p = json_data['port']
        try:
            port = int(p)
        except:
            self.send_response_only(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            message = {"success": False, "message": f"{p} is not a valid port"}

            body = json.dumps(message).encode('utf-8')
            body += "\n\n".encode("utf-8")
            self.send_response_only(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            return
        if port < 0 or port > 65535:
            self.send_response_only(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            message = {"success": False, "message": f"{p} is not a valid port"}

            body = json.dumps(message).encode('utf-8')
            body += "\n\n".encode("utf-8")
            self.send_response_only(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            return

        if 'protocol' not in json_data.keys():
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Rejected api Call: Invalid parameter of protocol")
            return b''

        p = json_data['protocol']
        protocol = p.lower()
        if protocol != "tcp" and protocol != "udp":
            self.send_response_only(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            message = {"success": False, "message": f"{p} is not a valid protocol"}

            body = json.dumps(message).encode('utf-8')
            body += "\n\n".encode("utf-8")
            self.send_response_only(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            return

        ip = self.client_address[0]

        res = self.server.firewall.check_firewalld_rule_exists(ip=ip, port=port, protocol=protocol)
        if res:
            message = {'success': False, 'message': "The rule already exists, there is no need to create it again."}
            body = json.dumps(message).encode('utf-8')
            body += "\n\n".encode("utf-8")
            self.send_response_only(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        res = self.server.firewall.add_firewalld_rule(ip=ip, port=port, protocol=protocol)
        body = json.dumps(res).encode('utf-8')
        body += "\n\n".encode("utf-8")
        self.send_response_only(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Tool:
    def __init__(self):
        pass

    def parse_args(self, argv):
        options = {}
        positionals = []

        for arg in argv:
            if arg.startswith('--'):
                if '=' in arg:
                    key, value = arg[2:].split('=', 1)
                    options[key] = value
                else:
                    options[arg[2:]] = True
            elif arg.startswith('-') and len(arg) > 1:
                for char in arg[1:]:
                    options[char] = True
            else:
                positionals.append(arg)

        return options, positionals

    def check_password(self, pwd):
        ok = (
            len(pwd) > 15 and
            any(c.islower() for c in pwd) and
            any(c.isupper() for c in pwd) and
            any(c.isdigit() for c in pwd)
        )
        return ok

    def get_linux_distribution(self):
        try:
            with open('/etc/os-release') as f:
                info = f.read().lower()
                if 'centos' in info:
                    return 'centos'
                elif 'ubuntu' in info:
                    return 'ubuntu'
                else:
                    return False
        except FileNotFoundError:
            return False


class Centos:
    def __init__(self):
        pass

    def get_netstat(self):
        cmd = ["ss", "-antp"]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                universal_newlines=True
            )
        except Exception as e:
            return set()

        peer_ips = set()
        lines = result.stdout.strip().split('\n')

        for line in lines:
            if 'ESTAB' in line:
                parts = line.split()
                if len(parts) >= 5:
                    peer = parts[4]
                    ip = peer.rsplit(':', 1)[0]
                    ip = ip.strip('[]')
                    peer_ips.add(ip)

        return peer_ips

    def add_firewalld_rule(self, ip, port, protocol='tcp'):
        zone = 'public'
        try:
            rich_rule = (
                f'rule family="ipv4" '
                f'source address="{ip}" '
                f'port port="{port}" protocol="{protocol}" '
                'log prefix="Scorcsoft_monkeyACL" level="info" '
                f'accept'
            )

            cmd = [
                'firewall-cmd', '--zone', zone, '--add-rich-rule', rich_rule
            ]
            command = ' '.join(cmd)
            print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Create rule: {command}')
            subprocess.check_call(cmd)

            cmd = [
                'firewall-cmd', '--permanent', '--zone', zone, '--add-rich-rule', rich_rule
            ]
            command = ' '.join(cmd)
            print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Create rule: {command}')
            subprocess.check_call(cmd)

            subprocess.check_call(['firewall-cmd', '--reload'])
            return {'success': True, 'message': f"Create firewalld rule success: {ip} --[{protocol}]--> {port}"}
        except:
            return {'success': False, 'exception': True,
                    'message': f"Create firewalld rule failed：{traceback.format_exc()}"}

    def remove_firewalld_rule(self, target_ip, zone='public'):
        tag = "Scorcsoft_monkeyACL"
        try:
            result = subprocess.check_output([
                'firewall-cmd', '--zone', zone, '--list-rich-rules'
            ], universal_newlines=True)

            rules = result.strip().splitlines()
            removed = False
            for rule in rules:
                if tag in rule and f'source address="{target_ip}"' in rule:
                    subprocess.call([
                        'firewall-cmd', '--zone', zone, '--remove-rich-rule', rule
                    ])
                    subprocess.call([
                        'firewall-cmd', '--permanent', '--zone', zone, '--remove-rich-rule', rule
                    ])
                    # print(f"Remove firewalld rule success：{rule}")
                    removed = True
            if removed:
                subprocess.check_call(['firewall-cmd', '--reload'])
                return {'success': True, 'message': 'Remove firewalld rule success'}
            else:
                return {'success': False, 'exception': False, 'message': 'Non-existent rules'}

        except:
            return {'success': False, 'exception': True, 'message': traceback.format_exc()}

    def get_ips_from_tagged_rules(self, zone='public'):
        tag = "Scorcsoft_monkeyACL"
        try:
            result = subprocess.check_output([
                'firewall-cmd', '--zone', zone, '--list-rich-rules'
            ], universal_newlines=True)
            rules = result.strip().splitlines()
            ip_list = []
            for rule in rules:
                if tag in rule:
                    match = re.search(r'source address="([^"]+)"', rule)
                    if match:
                        ip = match.group(1)
                        ip_list.append(ip)

            return {'success': True, 'data': ip_list}
        except Exception as e:
            return {'success': False, 'exception': True, 'message': str(e), 'error': traceback.format_exc()}

    def check_firewalld_rule_exists(self, ip, port, protocol='tcp', zone='public'):
        tag = "Scorcsoft_monkeyACL"
        try:
            result = subprocess.check_output([
                'firewall-cmd', '--zone', zone, '--list-rich-rules'
            ], universal_newlines=True)

            rules = result.strip().splitlines()

            ip_str = f'source address="{ip}"'
            port_str = f'port port="{port}" protocol="{protocol}"'

            for rule in rules:
                if tag in rule and ip_str in rule and port_str in rule:
                    return True

            return False

        except subprocess.CalledProcessError as e:
            return False


ascii_logo = """
                        _                       _____ _      
                       | |                /\   / ____| |     
  _ __ ___   ___  _ __ | | _____ _   _   /  \ | |    | |     
 | '_ ` _ \ / _ \| '_ \| |/ / _ \ | | | / /\ \| |    | |     
 | | | | | | (_) | | | |   <  __/ |_| |/ ____ \ |____| |____ 
 |_| |_| |_|\___/|_| |_|_|\_\___|\___ /_/    \_\_____|______|
                                  __/ |                      
                                 |___/                       

A lightweight, secure tool for dynamic firewall authorization
Designed for temporary access control and on-demand port opening via API automation.
"""


def help_message():
    print("")
    print(ascii_logo)
    print('Github: https://github.com/Scorcsoft/monkeyACL')
    print("")
    print("Options:")
    print("    -h,--help: \t Show this help message and exit")
    # print("    -a: \t\t Automatically create a firewall rule to allow access to monkeyACL HTTP API")
    print("\n")
    print("Required parameter:")
    print("    --cert=PATH_TO_CERT_FILE: \t Path of the SSL certificate file")
    print("    --key=PATH_TO_KEY_FILE: \t Path to the SSL private key file")
    print("    --auth=AUTH: \t\t API authentication")
    print("    --port=PORT: \t\t API HTTP port")
    print("    --url=URL: \t\t\t API URL")
    print("\n")
    print("Notes:")
    print("    For your server security, The length of the --auth parameter must be greater than 16, and it must contain uppercase letters, lowercase letters, numbers")
    print("    If you do not have a valid SSL certificate, you can run the following command to generate one:")
    print("    Command: openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes")
    print("\n")
    print("Example:")
    print("    python3 monkeyACL.py --auth='1*r^(5_N1rrbKo6e' --port=8080 --url='myapi' --cert=cert.pem --key=key.pem")
    print("\n\n")


def acl_recycle(firewall):
    print("[i] Automatically detect network connections and clean up unused rules.")
    while 1:
        netstat = firewall.get_netstat()
        rules = firewall.get_ips_from_tagged_rules()
        if rules["success"]:
            for ip in rules["data"]:
                if ip not in netstat:
                    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] The authorized IP: [{ip}] is not connected to this server, its permission will be removed.')
                    r = firewall.remove_firewalld_rule(target_ip=ip)
                    if r['success']:
                        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Successfully removed access permission for [{ip}]')
                    else:
                        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Failed to remove access permission for [{ip}], Reason: {r["message"]}')
                else:
                    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] The authorized IP: [{ip}] is connected to this server, its permission will be hold.')
        else:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Unable to retrieve rule list： {rules['message']}")
        time.sleep(60)


def main():
    if os.geteuid() != 0:
        print(ascii_logo)
        print('Github: https://github.com/Scorcsoft/monkeyACL')
        print(f"[!] Root privileges are required to manage firewalld.")
        return
    args = sys.argv[1:]
    if len(args) == 0:
        help_message()
        return
    tool = Tool()
    opts, pos = tool.parse_args(args)
    if 'h' in opts.keys() and opts['h']:
        help_message()
        return

    if 'auth' not in opts.keys():
        print('[!] You must to specify the -auth parameter for API authentication.')
        print('[i] Example: python3 monkeyACL.py --auth="fr#yrQ(7rsM8v)ra"')
        return

    if 'port' not in opts.keys():
        print('[!] You must to specify the -port parameter for API HTTP port.')
        print('[i] Example: python3 monkeyACL.py --port=8080')
        return

    if 'url' not in opts.keys():
        print('[!] You must to specify the -url parameter for API url.')
        print('[i] Example: python3 monkeyACL.py --url=myapi')
        return

    if 'cert' not in opts.keys():
        print('[!] You must to specify the -cert parameter for the SSL certificate file.')
        print('[i] Example: python3 monkeyACL.py --cert=cert.pem')
        return

    if 'key' not in opts.keys():
        print('[!] You must to specify the -cert parameter for the SSL private key file.')
        print('[i] Example: python3 monkeyACL.py --key=key.pem')
        return

    auth = opts["auth"]

    if not tool.check_password(auth):
        print(f"[!] {auth} is not a valid auth key")
        print('[!] For your server security, The length of the --auth parameter must be greater than 16, and it must contain uppercase letters, lowercase letters and numbers')
        print('[i] Example: python3 monkeyACL.py --auth="fr#yrQ(7rsM8v)ra"')
        print("more information: https://github.com/Scorcsoft/monkeyACL")
        return

    OPTIONS['auth'] = auth
    if 'port' not in opts.keys():
        print('[!] You must to specify the --port parameter for API HTTP Port.')
        print('[i] Example: python3 monkeyACL.py --port=8080')
        print("more information: https://github.com/Scorcsoft/monkeyACL")
        return

    p = opts['port']
    try:
        port = int(p)
    except:
        print("[!] —-port parameter must be an integer, which serves as the API HTTP port.")
        print('[i] Example: python3 monkeyACL.py --port=8080')
        print("more information: https://github.com/Scorcsoft/monkeyACL")
        return
    if port < 0 or port > 65535:
        print(f"[!] {p} is not a valid port")
        print('[!] You must to specify the -port parameter for API HTTP Port.')
        print('[i] Example: python3 monkeyACL.py --port=8080')
        print("more information: https://github.com/Scorcsoft/monkeyACL")

    OPTIONS['url'] = opts["url"]

    firewall = Centos()


    try:
        recycle = threading.Thread(target=acl_recycle, args=(firewall,), daemon=True)

        server = MonkeyACLServer(('', port), MonkeyACLHandler, firewall)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=opts['cert'], keyfile=opts['key'])
        server.socket = context.wrap_socket(server.socket, server_side=True)

        print(ascii_logo)
        print('Github: https://github.com/Scorcsoft/monkeyACL')
        print("")
        recycle.start()
        print(f"[i] MonkeyACL is running at: https://0.0.0.0:{port}/{opts['url']}")
        print(f"[i] If you cannot access the Monkey ACL API service, please run the following command:")
        print(f"sudo firewall-cmd --zone=public --add-port={opts['port']}/tcp --permanent")
        print(f"sudo firewall-cmd --reload")

        server.serve_forever()
    except KeyboardInterrupt:
        print("[i] User quit.")
        sys.exit(1)
    except OSError as e:
        if e.errno == 98:  # Linux "Address already in use"
            print(f"[!] 0.0.0.0:{port} already in use, please specify other port.")
        else:
            print(f"[!] MonkeyACL startup failed, {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[!] MonkeyACL startup failed, {e}")


if __name__ == '__main__':
    main()
