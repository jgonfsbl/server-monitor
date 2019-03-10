""" This is a server monitor microservice """

import sys
import os
import re
import argparse
import distutils.spawn
import threading
import socket
import smtplib
import datetime
import time
import urllib
import http.client as httplib


def prDate(string, indent):
    """ Print date in ISO 8601 format """
    strindent = ""
    for j in range(0, indent):
        strindent = strindent + " "
    print("[" + datetime.datetime.now().strftime("%Y%m%dT%H:%M:%S") +
          "]" + strindent + " " + string)


parser = argparse.ArgumentParser(
    description='Check if a host is alive.',
    formatter_class=lambda
    prog: argparse.HelpFormatter(prog, max_help_position=150, width=150))

parser.add_argument('-u', '--smtpuser',
                    help='The SMTP username', default='')
parser.add_argument('-p', '--smtppass',
                    help='The SMTP password', default='')
parser.add_argument('-l', '--smtpsubject',
                    help='The SMTP message subject',
                    default='Service status changed!')
parser.add_argument('-o', '--interval',
                    help='The interval in minutes between checks (def. 15)',
                    default=15, type=int)
parser.add_argument('-r', '--retry',
                    help='The retry count when a connection fails (def. 5)',
                    default=5, type=int)
parser.add_argument('-d', '--delay',
                    help='The retry delay in seconds when a connection fails \
                    (def. 10)', default=10, type=int)
parser.add_argument('-t', '--timeout',
                    help='The connection timeout in seconds (def. 3)',
                    default=3, type=int)
parser.add_argument('-y', '--pushoverapi',
                    help='The pushover.net API key', default='')
parser.add_argument('-z', '--pushoveruser',
                    help='The pushover.net User key', default='')

requiredArguments = parser.add_argument_group('required arguments')

requiredArguments.add_argument('-s', '--smtpserver',
                               help='The SMTP server:port', required=True)
requiredArguments.add_argument('-f', '--smtpfrom',
                               help='The FROM email address', required=True)
requiredArguments.add_argument('-k', '--smtpto',
                               help='The TO email address', required=True)
requiredArguments.add_argument('-m', '--monitor',
                               nargs='+',
                               help='The server / server list to monitor. \
                               Format: "<server>:<port> <server>:<port>:udp"',
                               required=True)
args = parser.parse_args()


def tcpCheck(ip, port):
    """ Check a TCP port """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, int(port)))
        s.shutdown(socket.SHUT_RDWR)
        return True
    except Exception:
        return False
    finally:
        s.close()


def udpCheck(ip, port):
    """ Check a UDP port """
    cmd = "nc -vzu -w " + str(timeout) + " " + ip + " " + \
        str(port) + " 2>&1"
    res = os.popen('DATA=$(' + cmd + ');echo -n $DATA').read()
    if res != "":
        return True
    else:
        return False


def checkHost(host):
    """ Execute the check """
    ipup = False
    for i in range(retry):
        if host["conntype"] == "udp":
            if udpCheck(host["ip"], host["port"]):
                ipup = True
                break
            else:
                prDate("No response from " + host["ip"] + ":" +
                       str(host["port"]) + ":" + host["conntype"] +
                       ", retrying in " + str(delay) + "s...", 0)
                time.sleep(delay)
        else:
            if tcpCheck(host["ip"], host["port"]):
                ipup = True
                break
            else:
                prDate("No response from " + host["ip"] + ":" +
                       str(host["port"]) + ":" + host["conntype"] +
                       ", retrying in " + str(delay) + "s...", 0)
                time.sleep(delay)
    return ipup


def sendMessage():
    """ Notification subroutine """
    prDate("Sending SMTP message", 2)
    message = "Subject: " + args.smtpsubject + "\r\n"
    message += "From: " + args.smtpfrom + "\r\n"
    message += "To: " + args.smtpto + "\r\n"
    message += "\r\n"

    for change in changes:
        message += change + ".\r\n"
    server = smtplib.SMTP(args.smtpserver)
    server.starttls()

    if args.smtpuser != '' and args.smtppass != '':
        server.login(args.smtpuser, args.smtppass)
    server.sendmail(args.smtpfrom, args.smtpto, message)
    server.quit()

    if args.pushoverapi != '' and args.pushoveruser != '':
        prDate("Sending Pushover message", 2)
        conn = httplib.HTTPSConnection("api.pushover.net:443")
        conn.request("POST", "/1/messages.json",
                     urllib.urlencode({
                         "token": args.pushoverapi,
                         "user": args.pushoveruser,
                         "message": message,
                         "sound": "falling",
                     }),
                     {"Content-type": "application/x-www-form-urlencoded"})
        conn.getresponse()


def parseHost(host):
    """ Host status comparison """
    prestatus = host["status"]
    prDate("Checking " + host["ip"] + ":" + str(host["port"]) +
           ":" + host["conntype"] + "...", 0)

    if checkHost(host):
        host["status"] = "up"
        if prestatus == "down":
            changes.append(host["ip"] + ":" + str(host["port"]) +
                           ":" + host["conntype"] + " is " + host["status"])
    else:
        host["status"] = "down"
        if prestatus == "up":
            changes.append(host["ip"] + ":" + str(host["port"]) +
                           ":" + host["conntype"] + " is " + host["status"])

    prDate("Status of " + host["ip"] + ":" + str(host["port"]) +
           ":" + host["conntype"] + ": " + host["status"], 0)


nc = distutils.spawn.find_executable("nc")
if not nc:
    prDate("Missing `nc`. Exiting", 0)
    sys.exit()

retry = args.retry
delay = args.delay
timeout = args.timeout
hosts = []

for host in args.monitor:
    conntype = "tcp"
    ipport = re.split('[:]', host)
    ip = ipport[0]
    port = int(ipport[1])

    if len(ipport) > 2:
        conntype = ipport[2]

    hosts.append({"ip": ip, "port": port, "conntype": conntype,
                  "status": "unknown"})


if __name__ == '__main__':
    """ Main loop """
    while True:
        changes = []
        threads = []

        for host in hosts:
            t = threading.Thread(target=parseHost, args=(host,))
            threads.append(t)

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        if len(changes) > 0:
            sendMessage()
            del changes[:]

        del threads[:]

        prDate("Waiting " + str(args.interval) +
               " minutes for next check.", 0)

        time.sleep(args.interval * 60)
