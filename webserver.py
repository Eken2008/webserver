import datetime
import socket
import logging
import pathlib
import os
from colorama import Fore, Style
import threading
from urllib.parse import unquote
import time
import re
import traceback
import websockets
import asyncio
from inspect import getsourcefile
from os.path import abspath
import sys

logging = logging.getLogger(__name__)

statuscodes={
    "100":"Continue",
    "101":"Switching Protocols",
    "102":"Processing",
    "103":"Early Hints",

    "200":"Ok",
    "201":"Created",
    "202":"Accepted",
    "203":"Non-Authoritative Information",
    "204":"No Content",
    "205":"Reset Content",
    "206":"Partial Content",
    "207":"Multi-Status",
    "208":"Already Reported",
    "226":"IM Used",

    "300":"Multiple Choices",
    "301":"Moved Permanently",
    "302":"Found",
    "303":"See Other",
    "304":"Not Modified",
    "305":"Use Proxy",
    "306":"Switch Proxy",
    "307":"Temporary Redirect",
    "308":"Permanent Redirect",

    "400":"Bad Request",
    "401":"Unauthorized",
    "402":"Payment Required",
    "403":"Forbidden",
    "404":"Not Found",
    "405":"Method Not Allowed",
    "406":"Not Acceptable",
    "407":"Proxy Authentication Required",
    "408":"Request Timeout",
    "409":"Conflict",
    "410":"Gone",
    "411":"Length Required",
    "412":"Precondition Failed",
    "413":"Payload Too Large",
    "414":"URI Too Long",
    "415":"Unsupported Media Type",
    "416":"Range Not Satisfiable",
    "417":"Expectation Failed",
    "418":"I'm a teapot",
    "421":"Misdirected Request",
    "422":"Unprocessable Entity",
    "423":"Locked",
    "424":"Failed Dependency",
    "425":"Too Early",
    "426":"Upgrade Required",
    "428":"Precondition Required",
    "429":"Too Many Requests",
    "431":"Request Header Fields Too Large",
    "451":"Unavailable For Legal Reasons",
    
    "500":"Internal Server Error",
    "501":"Not Implemented",
    "502":"Bad Gateway",
    "503":"Service Unavailable",
    "504":"Gateway Timeout",
    "505":"HTTP Version Not Supported",
    "506":"Variant Also Negotiates",
    "507":"Insufficient Storage",
    "508":"Loop Detected",
    "510":"Not Extended",
    "511":"Network Authentication Required",
}

months=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

__innerHTMLVal=""
def __innerHTML(value:str,html:bool=True):
    global __innerHTMLVal
    if html:
        __innerHTMLVal+=str(value).replace("\n","<br>")
    else:
        __innerHTMLVal+=str(value).replace("<","&lt;").replace("\n","<br>")

def __loadOther(path:str,template:bool=True):
    with open(str(pathlib.Path(os.path.dirname(os.path.abspath(sys.argv[0]))).resolve())+"/"+("templates/"*template)+path, encoding="utf-8") as f:
        __innerHTMLVal+=f.read()

def renderTemplateStr(data:str,status:str="200",contentType:str="text/html",vars:dict={}):
    global __innerHTMLVal
    regex="{%(?:(?!%})[\S\s])+%}"
    try:
        prevLoc=vars
        while True:
            __innerHTMLVal=""
            out=re.search(regex, data)
            loc = {"print":__innerHTML,"consolePrint":print,"app":APP,"loadOther":__loadOther}
            loc|=prevLoc
            exec(out.group(0)[2:-2], globals(), loc)
            prevLoc=loc
            data=data[0:out.start()]+__innerHTMLVal+data[out.end():]
    except AttributeError:
        pass
    return Response(html=data,status=status,contentType=contentType)


def renderTemplate(path:str,status:str="200",contentType:str="text/html",vars:dict={}):
    global __innerHTMLVal
    with open(str(pathlib.Path(os.path.dirname(os.path.abspath(sys.argv[0]))).resolve())+"/templates/"+path, "r", encoding="utf-8") as f:
        return renderTemplateStr(f.read(),status,contentType,vars)

def redirect(path:str,status:str="302"):
    resp=Response("",status)
    resp.headers+=f"Location:{path}\r\n"
    return resp

class Reqeust:
    def __init__(self,ip,method,url) -> None:
        self.ip=ip
        self.method=method
        self.url=url
        path = self.url.split("?")[0].split("#")[0]
        self.path=path
        self.query=""
        self.queryDict={}
        self.form={}
        self.headers={}
        self.cookies={}

class Response:
    def __init__(self,html:str,status:str="200",contentType:str="text/html") -> None:
        self.html=html
        self.status=status
        self.html=html
        self.headers=""

        self.ip=APP.request.ip
        self.method=APP.request.method
        self.path=APP.request.path
    def setCookie(self,name:str,value:str,expireDate:datetime.datetime="",domain:str="",path:str="/"):
        #if expireDate=="":
        #    expireDate=datetime.datetime(2100,1,1,0,0,0)
        date=f"; expires=Sat Feb 01 2025 00:00:00"#{expireDate.year}-{expireDate.month}-{expireDate.day}T{expireDate.hour}:{expireDate.minute}:{expireDate.second}.000+00:00"
        #date = "; expires="+str(int(time.mktime(expireDate.timetuple())) * 1000)
        if domain!="":
            domain="; domain="+domain
        if path!="":
            path="; path="+path
        self.headers+=f"Set-Cookie:{name}={value}"+date+domain+path+"\r\n"


class app:
    def __init__(self,host:str,port:int,clientLimit:int=10,wsPort=5050) -> None:
        global APP
        self.host = host
        self.port = port
        self.static = "static"
        self.paths = {}
        self.wspaths = {}
        APP=self
        self.clientLimit = clientLimit
        self.wsPort = wsPort

    def run(self):
        serverThread = threading.Thread(target=self.__run)
        serverThread.start()

        if self.wspaths != {}:
            self.lastWSclose=None
            wsServerThread = threading.Thread(target=asyncio.run, args=(self.__wsRun(),))
            wsServerThread.start()

        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            os._exit(0)
    
    @staticmethod
    def wsConnectionClose(ws,path,addr):
        logging.info("WEBSOCKET close on "+path+" by "+ws.remote_address[0])

    async def __wsHandler(self,websocket,path):
        while True:
            try:
                message = await websocket.recv()
                print()
                if path in list(self.wspaths.keys()):
                    resp = self.wspaths[path](websocket,message,path,websocket.remote_address)
                    if resp != None:
                        if isinstance(resp,str):
                            await websocket.send(resp)
                            logging.info(f"{websocket.remote_address[0]} - WEBSOCKET - "+path+" 200 OK")
                        else:
                            raise TypeError(f"The function for websocket {path} did not return a valid response")
                else:
                    logging.info(f"{websocket.remote_address[0]} - WEBSOCKET - "+path+" 404 NOT FOUND")
                    await websocket.send("404 NOT FOUND")
            #except websockets.exceptions.ConnectionClosedOK as e:
                #logging.info("websocket close on "+path)
                #self.wsConnectionClose(websocket,path)
                #await websocket.close()
            except Exception as e:
                if(isinstance(e,websockets.exceptions.ConnectionClosedOK)):
                    #if websocket!=self.lastWSclose:
                    self.wsConnectionClose(websocket,path,websocket.remote_address)
                    break
                        #self.lastWSclose=websocket
                else:
                    logging.info(f"{websocket.remote_address[0]} - WEBSOCKET - "+path+" 500 INTERNAL SERVER ERROR")
                    logging.error(f"{Fore.RED}{traceback.format_exc()}{Style.RESET_ALL}")
                    await websocket.send("500 INTERNAL SERVER ERROR")

    async def __wsRun(self):
        async with websockets.serve(self.__wsHandler, "0.0.0.0", self.wsPort):
            await asyncio.Future()

    def __run(self):

        self.s = socket.socket()
        self.s.bind((self.host, self.port))

        host=self.host
        if host=="0.0.0.0":
            host="localhost"
        port=":"+str(self.port)+"/"
        if str(port)==":80/":
            port="/"
        logging.info(f'Starting server on {self.host} port {self.port}');logging.info(f'The Web server URL for this would be http://{host}{port}')
        
        self.s.listen(self.clientLimit)

        while True:
            self.request = Reqeust(ip="0.0.0.0",method="GET",url="/400BADREQUEST")
            response = Response("<h1>500 Internal Server Error</h1>", "500")
            requestOK=False
            try:
                self.conn, (client_host, client_port) = self.s.accept()
                data=self.conn.recv(1000)
                url=data.decode().split(" ")[1]
                self.request=Reqeust(
                    ip=client_host,
                    method=data.decode().split(" ")[0],
                    url=url
                )
                requestOK=True

                #query params
                if len(url.split("?"))>1:
                    self.request.query=url.split("?")[1]
                    for i in self.request.query.split("&"):
                        if len(i.split("="))>1:
                            self.request.queryDict[unquote(i.split("=")[0],encoding="Windows-1252")]=unquote(i.split("=")[1],encoding="Windows-1252")

                #post form data
                if len(data.decode().split("\r\n\r\n"))>1:
                    formData=data.decode().split("\r\n\r\n")[1]
                    if formData.split("&") != [""]:
                        for i in formData.split("&"):
                            if len(i.split("="))>1:
                                self.request.form[unquote(i.split("=")[0],encoding="Windows-1252")]=unquote(i.split("=")[1],encoding="Windows-1252")
                
                #headers
                dataStr=data.decode()
                headersList = dataStr[dataStr.index("HTTP"):].split("\r\n")
                headers={}
                for i in headersList:
                    if len(i.split(":"))>1:
                        headers[i.split(":")[0].lstrip(" ").lower()]=i.split(":")[1].lstrip(" ")
                self.request.headers=headers
                if not "sec-websocket-version" in self.request.headers.keys():
                    #cookies
                    if "cookie" in list(self.request.headers.keys()):
                        cookieList=headers["cookie"].split(";")
                        for i in cookieList:
                            if len(i.split("="))>1:
                                self.request.cookies[i.split("=",maxsplit=1)[0].lstrip(" ")]=i.split("=",maxsplit=1)[1].lstrip(" ")

                    

                    if self.request.path.startswith("/"+self.static):
                        #return static content
                        try:
                            with open(os.path.dirname(os.path.abspath(sys.argv[0]))+self.request.path, "r", encoding="utf-8") as f:
                                response = Response(html=f.read())
                        except FileNotFoundError:
                            response=Response(html="<h1>404 Not Found</h1> The requested resource was not found on the server!",status="404")
                    else:
                        #return other
                        path = self.request.path
                        if self.request.path+"/" in list(self.paths.keys()):
                            path = self.request.path+"/"
                        if path in list(self.paths):
                            response=self.paths[path]()
                            if not isinstance(response,Response):
                                response=Response(html="<h1>500 Internal Server Error</h1>",status="500")
                                logging.error("500 Internal server error");logging.error(f"The function for \"{self.request.path}\" did not return a valid response")

                        else:
                            response=Response(html="<h1>404 Not Found</h1> The requested resource was not found on the server!",status="404")
                
            except Exception as e:
                if requestOK:
                    logging.error(f"{Fore.RED}{traceback.format_exc()}{Style.RESET_ALL}")
            
            try:
                if not "sec-websocket-version" in self.request.headers.keys():
                    if not requestOK:
                        response = Response("<h1>400 Bad request</h1>The server didn't understand the request, did you follow the HTTP protocol?",status="400")
                    html = response.html.encode(encoding="Windows-1252")
                    self.conn.send(('HTTP/1.0 '+str(int(response.status))+" "+statuscodes[response.status].upper()+'\n').encode())
                    self.conn.send(b'Server: BagottWebserver\n')
                    self.conn.send(b'Content-Length: '+str(len(html)).encode()+b'\n')
                    self.conn.send(b'Content-Type: text/html\n')
                    self.conn.send(response.headers.encode())
                    self.conn.send(b'\n')
                    self.conn.send(html)
                    self.conn.close()
            except AttributeError:
                try:
                    raise TypeError(f"Invalid return type of \"{type(response.html)}\"")
                except Exception:
                    logging.error(f"{Fore.RED}{traceback.format_exc()}{Style.RESET_ALL}")
            except ConnectionError as e:
                pass
            except Exception as e:
                logging.error(f"{Fore.RED}{traceback.format_exc()}{Style.RESET_ALL}")
            
            try:
                if not "sec-websocket-version" in self.request.headers.keys():
                    if requestOK:
                        color = ""
                        if response.status[0] == "4":
                            color = Fore.YELLOW
                        if response.status[0] == "5":
                            color = Fore.RED
                        if response.status[0] == "1":
                            color = Fore.BLUE
                        if response.status[0] =="3":
                            color = Fore.GREEN
                        logging.info(f"{color}{self.request.ip} - {self.request.method} {self.request.path}     -     {response.status} {statuscodes[response.status].upper()}{Style.RESET_ALL}")
            except Exception as e:
                logging.error("error while logging request info:",e)