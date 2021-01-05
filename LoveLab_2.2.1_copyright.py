import cgitb
import logging
import sys
import wx
import PyCapture2
import numpy as np
import threading
import wmi
import cv2
import wx.lib.buttons as buttons
import wx.adv
import time
import pickle
import pipython
from pipython import GCSError
from pipython import pitools
import wxmplot
import multiprocessing
import subprocess
import ctypes
from matplotlib import pyplot

localTime = time.localtime()
logger = logging.getLogger(__name__)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s: %(message)s')
file_handler = logging.FileHandler(".\\log\\log{}_{}_{}.log".format(localTime.tm_year, localTime.tm_mon, localTime.tm_mday))
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)
logger.info("App start")
# enabel expception captrue
cgitb.enable(display=0,logdir=".\\log\\bug\\",format='text')

# FindGigECamera will return any GigE camera information
def FindGigECamera():
    """returntype:List"""
    pointGraybus = PyCapture2.BusManager()
    gigECameraInfo = pointGraybus.discoverGigECameras()
    return gigECameraInfo

# Show GCSError in wx.MessageDialog
def ShowGCSErrorMessage(gcserror):
     wx.MessageDialog.ShowModal(wx.MessageDialog(parent=None, message="HexPod's Controller has error:\n{}"
                                                 .format(gcserror), style=wx.OK))

# Show other error in wx.MessageDialog
def ShowErrorMessage(exception):
    wx.MessageDialog.ShowModal(
        wx.MessageDialog(parent=None, message="{}".format(exception), style=wx.OK))

# Class to communicate with laser
class LaserTalker:
    def __init__(self):
        try:
            self.process = subprocess.Popen("ekspla_subprocess.exe", stdin=-1, stdout=-1, stderr=-1)
        except Exception as ex:
            raise(ex)

    def Connect(self):
        try:
            if self.SendCommand("test"):
                self.SendCommand("rcConnect 0 0")
        except Exception as ex:
            raise

    def SendCommand(self, command=""):
        try:
            command = command + "\n"
            self.process.stdin.write(command.encode())
            self.process.stdin.flush()
            retCode = self.process.stdout.readline().strip()
            if not retCode:
                errCode = self.process.stderr.readline()
                raise Exception(errCode.decode())
            return retCode.decode()
        except Exception as ex:
            raise

    def Terminnate(self):
        try:
            self.process.stdin.write(b"terminate\n")
            self.process.stdin.flush()
            self.process.terminate()
            logger.info("successfully terminnate laser subprocess")
            return 0
        except Exception as ex:
            raise


class FunctionButtons(buttons.GenBitmapButton):
    def __init__(self,name,*args,**kwargs):
        bmp = wx.Bitmap()
        bmp.LoadFile(name)
        super(FunctionButtons,self).__init__(bitmap=bmp,*args,**kwargs)
        self.SetBitmapFocus(bitmap=bmp)


class FunctionToggleButtons(buttons.GenBitmapToggleButton):
    def __init__(self, name, *args, **kwargs):
        bmp = wx.Bitmap()
        bmp.LoadFile(name)
        super(FunctionToggleButtons, self).__init__(bitmap=bmp, *args, **kwargs)
        self.SetBitmapFocus(bitmap=bmp)

    def SetBitmapSelected(self, name):
        bmp = wx.Bitmap()
        bmp.LoadFile(name)
        super(FunctionToggleButtons, self).SetBitmapSelected(bmp)


class App(wx.App):

    # App will first show a log in dialog
    def OnPreInit(self):
        # initialize ccd and hexpod(or motor)
        try:
            logger.info("start initializing gcs")
            self.MortorInit()
            logger.info("start initializing cameras")
            self.CcdInit()
            logger.info("start initializing laser")
            self.LaserInit()
        except Exception as exception:
            logger.error(exception)
        # App has a log in dialog which will get username and password
        # set default username
        self.username = "admin"
        self.logInDialog = App.LogInDialog(self)
        self.logInDialog.ShowModal()
        self.logInDialog.Destroy()
        logger.info("{} has logged in".format(self.username))
        # wait for controller ready
        while not self.gcs.IsControllerReady():
            pass
        logger.info("gcs successfully find reference point")

    # App will bootstrap mainApp
    def __init__(self):
        super(App, self).__init__()
        # App has a MainApp()
        self.mainFrame = MainFrame(self.gigECameraInfo, self.gcs, self.laser, self.username)

    # CcdInitThread will Find all camera, which either connected by GigE or USB,by using FindMainCamera and
    # FindUSBCamera met
    def CcdInit(self):
        # find GigE camera information
        logger.info("finding gigE camera")
        self.gigECameraInfo = FindGigECamera()
        # keep find main camera unless user don't want try
        while not len(self.gigECameraInfo):
            # show the "another try dialog"
            if wx.MessageDialog.ShowModal(
                    wx.MessageDialog(parent=None, message="Main camera haven't found.\nMake sure main camera is power "
                                                          "on and connected\nWant a another try?", style=wx.YES_NO)) \
                    == wx.ID_YES:
                self.gigECameraInfo = FindGigECamera()
            else:
                break
        logger.info("successfully find GigE camera")

    # MotorInit will find PI hexpod controller--"C-887". It will be a properties, named "gcs"
    def MortorInit(self):
        # use GCS command to connect controller
        self.GCSconnected = False
        self.gcs = pipython.GCSDevice("C-887")
        while not self.GCSconnected:
            try:
                self.gcs.ConnectRS232(4, 115200)
                self.GCSconnected = True
                logger.info("successfully connect GCSDevice")
            except GCSError as gcserror:
                if wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None, message="HexPod's Controller has error:\n{}\nWant a another try?"
                                .format(gcserror), style=wx.YES_NO)) \
                        == wx.ID_YES:
                    continue
                else:
                    logger.info("user refused connect GCSDevice")
                    return -1
        # use pitools to startup
        try:
            logger.info("gcs try to find reference point")
            self.gcs.FRF(["X", "Y", "Z", "U", "V", "W"])
        except GCSError as gcserror:
            wx.MessageDialog.ShowModal(
                wx.MessageDialog(parent=None, message="HexPod's Controller has error:\n{}\nWant a another try?"
                                 .format(gcserror), style=wx.OK))
            logger.error("gcserror occurred when find reference point because\n:{}".format(gcserror))

    def LaserInit(self):
        """laser init will open a subprocess to run ekspla_subprocess, which is a 32bit excutable file"""
        self.laser = LaserTalker()
        while True:
            try:
                logger.info("try to connecting laser")
                self.laser.Connect()
                logger.info("successfully connect laser")
                break
            except Exception as ex:
                logger.error("failed connect laser because:{}".format(ex))
                if wx.MessageDialog.ShowModal(
                     wx.MessageDialog(parent=None, message="Failed to connect laser,because:\n"
                                                          "{}"
                                                          "\nWant a another try?".format(ex),style=wx.YES_NO)) == wx.ID_YES:
                    pass
                else:
                    logger.info("user refuse connect laser")
                    return

    class LogInDialog(wx.Dialog):
        #  A LogInDialog can enter your username and password, then check them whether they are correct.
        #  It also allow new user to create account.
        def __init__(self, parent):
            super(App.LogInDialog, self).__init__(parent=None, title="Pleas log in")
            # add parent
            self.parent = parent
            # LogInDilog has a username Input control
            self.usernameTest = wx.StaticText(parent=self, label="username")
            self.usernameTextEntry = wx.TextCtrl(parent=self, style=wx.TE_PROCESS_ENTER)
            # LogInDilog has a password input contor
            self.passwordText = wx.StaticText(parent=self, label="password")
            self.passwordTextEntry = wx.TextCtrl(parent=self, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
            # LogInDialog has a createAccount control to call createAccount
            self.createAccountText = wx.StaticText(parent=self, label="Create your account?")
            # static line
            self.staticLine = wx.StaticLine(parent=self, size=(500, 1))
            # add button
            self.buttonPanel = wx.Panel(parent=self)
            self.buttonPanel.OKButton = wx.Button(parent=self.buttonPanel, label="OK")
            self.buttonPanel.cancelButton = wx.Button(parent=self.buttonPanel, label="Cancel")
            self.buttonPanel.Sizer = wx.BoxSizer()
            self.buttonPanel.Sizer.AddMany([(self.buttonPanel.OKButton, 0, wx.RIGHT, 10),
                                            (self.buttonPanel.cancelButton, 0, wx.RIGHT, 10)])
            # Add sizer item
            self.Sizer = wx.BoxSizer(wx.VERTICAL)
            self.Sizer.AddMany([(self.usernameTest, 0, wx.ALIGN_LEFT | wx.ALL, 10),
                                (self.usernameTextEntry, 0, wx.EXPAND | wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT, 15),
                                (self.passwordText, 0, wx.ALIGN_LEFT | wx.ALL, 10),
                                (self.passwordTextEntry, 0, wx.EXPAND | wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT, 15),
                                (self.createAccountText, 0, wx.ALIGN_RIGHT | wx.ALL, 10),
                                (self.staticLine, 0, 0, 0),
                                (self.buttonPanel, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
                                ])
            self.Center()
            # Bind event
            self.createAccountText.Bind(wx.EVT_LEFT_DOWN, self.CreateAccount)
            self.Bind(wx.EVT_BUTTON, self.CheckPassword, self.buttonPanel.OKButton)
            self.Bind(wx.EVT_BUTTON, self.OnClose, self.buttonPanel.cancelButton)
            self.usernameTextEntry.Bind(wx.EVT_TEXT_ENTER, self.CheckPassword)
            self.passwordTextEntry.Bind(wx.EVT_TEXT_ENTER, self.CheckPassword)
            self.Bind(wx.EVT_CLOSE, self.OnClose)
            # Log Dialog will have a CreatAccountDialog to creat account
            self.createAccountDialog = App.LogInDialog.CreateAccountDialog()

        def CheckPassword(self, event):
            # load user profile from userProfile.pkl
            try:
                file = open(".\\data\\userProfile.pkl", "rb")
                userDictionary = pickle.load(file)
                file.close()
            except FileNotFoundError as filenotfounderror:
                if wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None, message=filenotfounderror,
                                         style=wx.OK)) == wx.ID_OK:
                    userDictionary = {"admin": "admin"}
                    with open(".\\data\\userProfile.pkl", "wb+") as file:
                        pickle.dump(userDictionary, file, 4)
            # read user profile from Dialog
            username = self.usernameTextEntry.GetValue()
            password = self.passwordTextEntry.GetValue()
            passwordInDictionary = userDictionary.get(username)
            # check user profile
            if passwordInDictionary:  # if userDictionary has this user
                if password == passwordInDictionary:
                    self.parent.username = username
                    self.createAccountDialog.Destroy()
                    self.EndModal(retCode=True)
                else:
                    self.message = wx.MessageDialog(parent=None, message="You've entered uncorrected password",
                                                    style=wx.OK)
                    self.message.ShowModal()
            else:  # if userDictionary doesn't have this user
                self.message = wx.MessageDialog(parent=None,
                                                message="Can't find your account.Maybe you need create one "
                                                        "first", style=wx.OK)
                self.message.ShowModal()

        def CreateAccount(self, event):
            # If user need create account, end LogInDialog(which may not necessary ) and show the CreatAcoountDialog
            logger.info("user try to creat account")
            self.createAccountDialog.ShowModal()

        def OnClose(self, event):
            self.Destroy()
            sys.exit()

        class CreateAccountDialog(wx.Dialog):
            def __init__(self):
                super(App.LogInDialog.CreateAccountDialog, self).__init__(parent=None, title="Create your account")
                # add item
                self.usernameTest = wx.StaticText(parent=self, label="username")
                self.usernameTextEntry = wx.TextCtrl(parent=self, style=wx.TE_PROCESS_ENTER)
                self.passwordText = wx.StaticText(parent=self, label="password")
                self.passwordTextEntry = wx.TextCtrl(parent=self, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
                # static line
                self.staticLine = wx.StaticLine(parent=self, size=(500, 1))
                # add button
                self.buttonPanel = wx.Panel(parent=self)
                self.buttonPanel.OKButton = wx.Button(parent=self.buttonPanel, label="OK")
                self.buttonPanel.cancelButton = wx.Button(parent=self.buttonPanel, label="Cancel")
                self.buttonPanel.Sizer = wx.BoxSizer()
                self.buttonPanel.Sizer.AddMany([(self.buttonPanel.OKButton, 0, wx.RIGHT, 10),
                                                (self.buttonPanel.cancelButton, 0, wx.RIGHT, 10)])
                # Add sizer item
                self.Sizer = wx.BoxSizer(wx.VERTICAL)
                self.Sizer.AddMany([(self.usernameTest, 0, wx.ALIGN_LEFT | wx.ALL, 10),
                                    (self.usernameTextEntry, 0, wx.EXPAND | wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT, 15),
                                    (self.passwordText, 0, wx.ALIGN_LEFT | wx.ALL, 10),
                                    (self.passwordTextEntry, 0, wx.EXPAND | wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT, 15),
                                    (self.staticLine, 0, wx.TOP, 15),
                                    (self.buttonPanel, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
                                    ])
                self.Center()
                # Bind event
                self.Bind(wx.EVT_BUTTON, self.WriteAccount, self.buttonPanel.OKButton)
                self.Bind(wx.EVT_BUTTON, self.OnClose, self.buttonPanel.cancelButton)
                self.usernameTextEntry.Bind(wx.EVT_TEXT_ENTER, self.WriteAccount)
                self.passwordTextEntry.Bind(wx.EVT_TEXT_ENTER, self.WriteAccount)

            def OnClose(self, event):
                logger.info("create account dialog has been canceled")
                self.EndModal(retCode=False)

            def WriteAccount(self, event):
                # load user profile
                file = open(".\\data\\userProfile.pkl", "rb+")
                userDictionary = pickle.load(file)
                file.close()
                # write account
                username = self.usernameTextEntry.GetValue()
                password = self.passwordTextEntry.GetValue()
                if username in userDictionary:
                    self.message = wx.MessageDialog(parent=None, message="Username has already been registed ",
                                                    style=wx.OK)
                    self.message.ShowModal()
                elif username == "":
                    self.message = wx.MessageDialog(parent=None, message="Username can't be empty",
                                                    style=wx.OK)
                    self.message.ShowModal()
                elif password == "":
                    self.message = wx.MessageDialog(parent=None, message="Password can't be empty",
                                                    style=wx.OK)
                    self.message.ShowModal()
                else:
                    userDictionary.setdefault(username, password)
                    # save new account in userProfile
                    file = open(".\\data\\userProfile.pkl", "wb+")
                    pickle.dump(userDictionary, file, 4)
                    file.close()
                    self.message = wx.MessageDialog(parent=None, message="Account has been create successfully",
                                                    style=wx.OK)
                    self.message.ShowModal()
                    logger.info("{}'s account has been create successfully".format(username))
                    self.EndModal(retCode=True)


class MainFrame(wx.Frame):

    def __init__(self, gigECameraInfo=None, gcs=None, laser=None, username="admin"):
        # initialize camera properties
        self.gigECameraInfo = gigECameraInfo
        # initialize hexpod properties
        self.gcs = gcs
        # initialize laser properties
        self.laser = laser
        # initialize username
        self.username = username
        # MainApp first initialize GUI
        self.InitUI()
        # MainApp has a main Camera thread which will display at main camera window
        self.mainCameraThread = threading.Thread(target=self.MainCameraThread, name='MainCamera')
        # MainApp has a hexpod thread to read hexpod position
        self.hexpodPositionThread = threading.Thread(target=self.HexpodPostionThread,name="HexpodPostion")
        # MainApp show his GUI
        #self.ShowFullScreen(show=True)
        self.ShowFullScreen(show=True)
        self.SetMenuBar(self.menuBar)
        # MainApp start his camera threading and HexpodPostionThread
        self.mainCameraThreadFlag = True
        self.hexpodPositionThreadFlag = True
        self.mainCameraThread.setDaemon(True)
        self.hexpodPositionThread.setDaemon(True)
        self.mainCameraThread.start()
        self.hexpodPositionThread.start()
        # Bind event
        self.Bind(wx.EVT_BUTTON,self.StartClose,self.mainCameraPanel.closeButton)
        self.Bind(wx.EVT_CLOSE,self.OnClose)
        self.Bind(wx.EVT_MENU,self.StartClose,self.quitMenuItem)
        self.Bind(wx.EVT_MENU,self.ScaleDialogOpen,self.scaleMenuItem)
        self.Bind(wx.EVT_MENU, self.mainCameraPanel.TakePicture, self.cameraCaptureItem)

    def InitUI(self):
        # Init Frame
        super(MainFrame, self).__init__(parent=None, id=-1, pos=(-1, -1), size=(1600, 1200))
        # MainApp has a ccdWindow which is used to monitor sample surface and to control motor. It use the PointGray
        # Blackfly BFLY-PGE-20E4M camera, serial number:17430467,which is the first camera in self.GigECameraInfo
        self.mainCameraPanel = MainCameraPanel(camera=self.gigECameraInfo[0], gcs=self.gcs,
                                               laser=self.laser, username=self.username,
                                               parent=self, id=-1, size=(1600, 1200))
        # Main Frame has a wxBoxSizer for auto adjust widgets size
        self.boxSizer = wx.BoxSizer()
        self.boxSizer.Add(window=self.mainCameraPanel, proportion=0, flag=wx.SHAPED | wx.ALL, border=10)
        # Main Frame has menu bar
        self.menuBar = wx.MenuBar()
        self.fileMenu = wx.Menu()
        # add item to file menu
        self.scaleMenuItem = wx.MenuItem(parentMenu=self.fileMenu, id=wx.ID_ANY, text="&Scale",
                                         helpString="set scale if you've changed the objective lens")
        self.cameraCaptureItem = wx.MenuItem(parentMenu=self.fileMenu, id=wx.ID_ANY, text="&Capture",
                                             helpString="take a picture from main camera")
        bmp = wx.Bitmap()
        bmp.LoadFile(".\\icon\\camera.bmp")
        self.cameraCaptureItem.SetBitmap(bmp=bmp)
        # add quit item
        self.quitMenuItem = wx.MenuItem(self.fileMenu, id=wx.ID_EXIT, text="&Quit")
        self.quitMenuItem.SetBitmap(wx.ArtProvider.GetBitmap(wx.ART_QUIT, client=wx.ART_MENU, size=(20, 20)))
        #  append all
        self.fileMenu.Append(self.scaleMenuItem)
        self.fileMenu.Append(self.cameraCaptureItem)
        self.fileMenu.AppendSeparator()
        self.fileMenu.Append(self.quitMenuItem)
        # set menubar
        self.menuBar.Append(self.fileMenu, title="&File")

        # Main Frame will have a scale single choices dialog
        self.scaleDialog = wx.SingleChoiceDialog(parent=None, message="choose scale", caption="scale dialog",
                                                choices=["None", "200um", "500um"])

    def MainCameraThread(self):
        # Main camera thread will continue show live stream from camera
        while self.mainCameraThreadFlag is True:
            # show live stream from camera
            try:
                self.mainCameraPanel.RetriveOneFrame()
            except PyCapture2.Fc2error as fc2error:
                continue
            self.mainCameraPanel.ImageProcessing()
            self.mainCameraPanel.ShowOneFrame()

    def HexpodPostionThread(self):
        window = self.mainCameraPanel.queryPostionWindow
        while self.hexpodPositionThreadFlag is True:
            try:
                    pos = self.gcs.qPOS(["X","Y","Z"])
                    window.posx = round(pos["X"],3)
                    window.posy = round(pos["Y"],3)
                    window.posz = round(pos["Z"],3)
                    window.xpostionStaticText.SetLabel("X :{}/mm".format(window.posx))
                    window.ypostionStaticText.SetLabel("Y :{}/mm".format(window.posy))
                    window.zpostionStaticText.SetLabel("Z :{}/mm".format(window.posz))
            except  GCSError as gcserror:
                pass
            # at least sleep 1/5 sec
            time.sleep(1/60)

    def StartClose(self,event):
        self.Close()

    def OnClose(self, event):
        self.mainCameraPanel.setLaserDialog.PowerOff()
        while True in self.gcs.IsMoving(axes=["X", "Y", "Z", "U", "V", "W"]).values():
            # if wave generator is moving, stop it
            if True in self.gcs.qWGO([1, 2, 3]).values():
                self.mainCameraPanel.circleDialog.runThread.stopFlage = True
                break
            self.gcs.HLT(axes=["X", "Y", "Z", "U", "V", "W"], noraise=True)
        if wx.MessageDialog.ShowModal(
                wx.MessageDialog(parent=self, message="Do you want to quit?", style=wx.YES_NO | wx.STAY_ON_TOP)) \
                == wx.ID_YES:
            # kill all thread and process
            self.mainCameraPanel.cameraThreadFlag = False
            self.mainCameraPanel.hexpodPositionThread = False
            # move to the save position
            try:
                zpos = self.gcs.qNLM("Z")
                self.gcs.MOV({"X": 0, "Y": 0, "Z": zpos["Z"]})
            except GCSError as gcserror:
                ShowGCSErrorMessage(gcserror)
            # release other resource
            self.mainCameraPanel.setLaserDialog.PowerOff()
            self.laser.Terminnate()
            self.mainCameraPanel.gcs.CloseConnection()
            self.scaleDialog.Destroy()
            self.Destroy()
        else:
            event.Veto()

    def ScaleDialogOpen(self,event):
        if self.scaleDialog.ShowModal() == wx.ID_OK:
            n = self.scaleDialog.GetSelection()
            if n == 0:
                self.mainCameraPanel.DrawCorssHairFlag = False
            elif n == 1:
                self.mainCameraPanel.DrawCorssHairFlag = True
                self.mainCameraPanel.scaleRange = 200
                self.mainCameraPanel.scale = 5
            elif n == 2:
                self.mainCameraPanel.DrawCorssHairFlag = True
                self.mainCameraPanel.scaleRange = 500
                self.mainCameraPanel.scale = 10
            self.scaleDialog.Hide()
        else:
            self.scaleDialog.Hide()


class CameraPanel(wx.Panel):

    # A CameraPanel is a wxPanel and it will show live stream form Ccd
    def __init__(self, camera, *args, **kwargs):
        """camera = PyCapture2.CameraInfo or CIM_USBController
        cameraType = GigE for PyCapture2.CameraInfo or USBPnP for CIM_USBController
        *args and **kwargs for wx.Window() class"""
        # init Panel
        super(CameraPanel, self).__init__(*args, **kwargs)
        # CcdPanel has a cv2::VideoCapture,name::cap,camNum indicate the camera number you want to capture in which
        # the numbers that cv2 has found
        bus = PyCapture2.BusManager()
        self.uID = bus.getCameraFromSerialNumber(camera.serialNumber)
        self.cam = PyCapture2.GigECamera()
        self.cam.connect(self.uID)
        self.cam.startCapture()
        # CameraPanel has a wxClient DC use to show frame on it self
        self.clientDC = wx.ClientDC(self)
        # CcdPanel has a wx.Bitmap to safe frame
        self.bitmap = wx.Bitmap()
        # CameraPanel has same calibrate properties to indicate how frame should be processed
        self.rotator = 0
        self.pos = [0,0]
        self.expend = 2
        # CameraPanel has a standard to indicate how long(um) a pixel is
        self.standard = 1

    # A CameraPanel can retrieve one frame by using it's cap.And then, save it in it's bitmap
    def RetriveOneFrame(self):
        # if use GigE camera, raw data that retrieve from camera buffer need reshape to bitmap
        data = self.cam.retrieveBuffer()
        frame = np.reshape(data.getData(), (data.getRows(), data.getCols()))
        self.rowFrame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        self.frame = self.rowFrame
        self.rowWidth, self.rowHeight = self.rowFrame.shape[:2]

    # A CaeraPanel may processing its image obtained from RetriveOneFrame method before show it
    def ImageProcessing(self):
        # expand
        if self.expend != 1:
            self.frame = self.Expend(self.frame)
        # rotation
        if self.rotator != 0:  # rotation
            self.frame = self.Rotate(self.frame)
        # cut and move
        if self.pos != [0, 0]:
            self.frame = self.Cutting(self.frame)
        self.width, self.height = self.frame.shape[:2]

    # image process methods
    def Rotate(self,frame):
        width,height = self.frame.shape[:2]
        rotationMarix = cv2.getRotationMatrix2D((height/2,width/2),self.rotator,scale=1)
        frame = cv2.warpAffine(frame,rotationMarix,(height,width))
        return frame

    def Expend(self, frame):
        dim = (self.rowHeight * self.expend, self.rowWidth * self.expend)
        frame = cv2.resize(frame, dim, interpolation=cv2.INTER_LINEAR)
        return frame

    def Cutting(self,frame):
        height,width = self.ClientSize
        frame = frame[self.pos[1]:self.pos[1]+width, self.pos[0]:self.pos[0]+height]
        return frame

    # A CameraPanel can show one Frame when captured
    def ShowOneFrame(self):
        self.bitmap = wx.Bitmap.FromBuffer(self.height, self.width,
                                           self.frame * 1)  # WHAT THE FUCK!!! unless do somthing to frame(say * 1), if just cut, and it will be error. properly somthin wrong with numpy or wxbitmap
        self.clientDC.DrawBitmap(bitmap=self.bitmap, x=-1, y=-1)

    # A CameraPanel can take picture
    def TakePicture(self,event):
        bitmap = np.copy(self.rowFrame)
        pyplot.imshow(bitmap)
        pyplot.xticks([])
        pyplot.yticks([])
        pyplot.show()


class MainCameraPanel(CameraPanel):

    def __init__(self, camera, gcs, laser=None, username=None, *args, **kwargs):
        super(MainCameraPanel, self).__init__(camera, *args, **kwargs)
        # initialize gcs
        self.gcs = gcs
        # initialize laser
        self.laser = laser
        # initialize username
        self.username = username
        # initialize scale range, default range is 200um and 5 for each
        self.scaleRange = 500
        self.scale = 10
        # set home postion
        try:
            file = open(".\\data\\{}home.pkl".format(self.username), "rb")
            self.home = pickle.load(file)
            file.close()
        except FileNotFoundError:
            if wx.MessageDialog.ShowModal(
                    wx.MessageDialog(parent=None,
                                     message="Can't find {}'s home,Want to continue?".format(self.username),
                                     style=wx.OK)) == wx.ID_OK:
                self.home = (0, 0)
                pass
        # set focus plan position and visual plan
        try:
            file = open(".\\data\\{}focusPlan.pkl".format(self.username), "rb")
            self.focusPlan = pickle.load(file)
            self.visualPlan = pickle.load(file)
            file.close()
        except FileNotFoundError:
            if wx.MessageDialog.ShowModal(
                    wx.MessageDialog(parent=None,
                                     message="Can't find {}'s focusPlan,Want to continue?".format(self.username),
                                     style=wx.OK)) == wx.ID_OK:
                self.focusPlan = {"Z": 0}
                pass
            self.focusPlan = {"Z":0}
            self.visualPlan = {"Z":0}
        # set motor pos
        self.motorPos = self.gcs.qPOS()
        # set mainCameraPanel properties from data file
        try:
            file = open(".\\data\\{}mainCameraCalibrate.pkl".format(self.username), "rb")
            self.expend = pickle.load(file)
            self.rotator = pickle.load(file)
            self.pos = pickle.load(file)
            file.close()
        except FileNotFoundError:
            if wx.MessageDialog.ShowModal(
                    wx.MessageDialog(parent=None,
                                     message="Can't find {}'s mainCameraCalibrate,"
                                             "Want to continue?".format(self.username),
                                     style=wx.OK)) == wx.ID_OK:
                self.expend = 2
                self.rotator = 0
                self.pos = [0, 0]
                pass
        # set mainCameraPanel standard
        try:
            file = open(".\\data\\{}mainCameraStandardization.pkl".format(self.username), "rb")
            self.standard = pickle.load(file)
            file.close()
        except FileNotFoundError:
            if wx.MessageDialog.ShowModal(
                    wx.MessageDialog(parent=None,
                                     message="Can't find {}'s mainCameraStandardization,"
                                             "Want to continue?".format(self.username),
                                     style=wx.OK)) == wx.ID_OK:
                self.standard = 1000
                pass
        # Main camera panel has few function button
        self.homeButton = FunctionButtons(parent=self, name=".\\icon\\gohome.bmp")
        self.setHomeButton = FunctionButtons(parent=self, name=".\\icon\\setgohome.bmp")
        self.stepMoveButton = FunctionToggleButtons(parent=self, name=".\\icon\\stepmove.bmp")
        self.stepMoveButton.SetBitmapSelected(name=".\\icon\\stepmoveON.bmp")
        self.calibratButton = FunctionToggleButtons(parent=self, name=".\\icon\\calibrate.bmp")
        self.calibratButton.SetBitmapSelected(name=".\\icon\\calibrateON.bmp")
        self.standardizationButton = FunctionToggleButtons(parent=self, name=".\\icon\\standardization.bmp")
        self.standardizationButton.SetBitmapSelected(name=".\\icon\\standardizationON.bmp")
        self.laserSpotTriggerButton = FunctionToggleButtons(parent=self, name=".\\icon\\back_focuplan.bmp")
        self.laserSpotTriggerButton.SetBitmapSelected(name=".\\icon\\back_focuplanON.bmp")
        self.setFocusPlaneButton = FunctionToggleButtons(parent=self, name=".\\icon\\set_focuplan.bmp")
        self.setFocusPlaneButton.SetBitmapSelected(name=".\\icon\\set_focuplanON.bmp")
        self.findFocusPlaneButton = FunctionToggleButtons(parent=self, name=".\\icon\\findfocusplan.bmp")
        self.findFocusPlaneButton.SetBitmapSelected(name=".\\icon\\findfocusplanON.bmp")
        self.zigZagButton = FunctionToggleButtons(parent=self, name=".\\icon\\zigzag.bmp")
        self.zigZagButton.SetBitmapSelected(name=".\\icon\\zigzagON.bmp")
        self.circleButton = FunctionToggleButtons(parent=self, name=".\\icon\\circle.bmp")
        self.circleButton.SetBitmapSelected(name=".\\icon\\circleON.bmp")
        self.setLaserButton = FunctionToggleButtons(parent=self, name=".\\icon\\set_laser.bmp")
        self.setLaserButton.SetBitmapSelected(name=".\\icon\\set_laserON.bmp")
        self.closeButton = FunctionButtons(parent=self, name=".\\icon\\close.bmp")
        # Main camera panel has static text window to quot hexpod position
        self.queryPostionWindow = MainCameraPanel.QueryPostionWindow(parent=self, size=(81, 84))
        # Main camera panel has a step move dialog to step move
        self.stepMoveDialog = MainCameraPanel.StepMoveDialog(self)
        # Main camera panel has a circle dialog
        self.circleDialog = MainCameraPanel.CircleDialog(self)
        # Main camera panel has a calibrate dialog
        self.calibrateDialog = MainCameraPanel.CalibrateDialog(self)
        # Main camera panel has a set Laser dialog
        self.setLaserDialog = MainCameraPanel.SetLaserDialog(self)
        # Main camera panel has a set focuse plan dialog
        self.setFocusPlanDialog = self.SetFocusPlanDialog(self)
        # Main camera panel has a set auto find focuse plan dialog
        self.findFocusPlaneDialog = self.AutoFindFocuseDialog(self)
        # Main camera panel has a zig zag dialog
        self.zigZagDialog = self.ZigZagDialog(self)
        # Main camera has a Sizer to arrange space
        self.Sizer = wx.BoxSizer()
        self.sizerFlag = wx.SizerFlags(1).Bottom()
        self.Sizer.AddMany(
            [(self.queryPostionWindow, 1, wx.ALIGN_LEFT | wx.TOP, 2), (1, 0, 1, 0), (self.homeButton, self.sizerFlag),
             (self.setHomeButton, self.sizerFlag),
             (self.stepMoveButton, self.sizerFlag), (self.calibratButton, self.sizerFlag),
             (self.standardizationButton, self.sizerFlag), (self.laserSpotTriggerButton, self.sizerFlag),
             (self.setFocusPlaneButton, self.sizerFlag), (self.findFocusPlaneButton, self.sizerFlag),
             (self.zigZagButton, self.sizerFlag), (self.circleButton, self.sizerFlag),
             (self.setLaserButton, self.sizerFlag), (1, 0, 1, 0), (self.closeButton, 1, wx.ALIGN_RIGHT, 0)])
        # Bind mouse event. When left dragging, motor move x and y. When left double click, move to the point. When
        # scroll rolling, motor move z. When scroll dragging, motor move z continually.
        self.startPos = (0, 0)
        self.endPos = (0, 0)
        self.movVector = (0, 0)
        self.Zmov = 0
        self.ZmovSpeed = 0
        self.standardpoints = []
        # Bind all function button event
        self.Bind(wx.EVT_BUTTON, self.Calibrate, self.calibratButton)
        self.Bind(wx.EVT_BUTTON, self.Standardization, self.standardizationButton)
        self.Bind(wx.EVT_BUTTON, self.GoHome, self.homeButton)
        self.Bind(wx.EVT_BUTTON, self.SetHome, self.setHomeButton)
        self.Bind(wx.EVT_BUTTON, self.LaserSpotTrigger, self.laserSpotTriggerButton)
        self.Bind(wx.EVT_BUTTON, self.SetFocusPlane, self.setFocusPlaneButton)
        self.Bind(wx.EVT_BUTTON, self.StepMove, self.stepMoveButton)
        self.Bind(wx.EVT_BUTTON, self.Circle, self.circleButton)
        self.Bind(wx.EVT_BUTTON, self.SetLaser, self.setLaserButton)
        self.Bind(wx.EVT_BUTTON, self.AutoFindFocusePlan, self.findFocusPlaneButton)
        self.Bind(wx.EVT_BUTTON, self.ZigZagProcess, self.zigZagButton)
        # Bind all mouse left event
        self.Bind(wx.EVT_LEFT_DOWN, self.GetStartPos)
        self.Bind(wx.EVT_LEFT_UP, self.UnbindMotionEvent)
        self.Bind(wx.EVT_LEFT_DCLICK, self.MovetoPoint)
        # Bind all mouse middle event
        self.Bind(wx.EVT_MIDDLE_DOWN, self.GetStartPos)
        self.Bind(wx.EVT_MIDDLE_UP, self.UnbindMotionEvent)
        self.Bind(wx.EVT_MOUSEWHEEL, self.MoveZaxis)
        # set flage
        self.calibrateFlage = False
        self.standardizationFlag = False
        self.DrawCorssHairFlag = True
        # GetStartPos, GetEndPos, UnbindMotionEvent will combined together to get self.movVector or self.ZmovSpeed

    def GetStartPos(self, event):
        self.startPos = event.Position
        self.motorPos = self.gcs.qPOS()
        if self.calibrateFlage is True:
            self.startrotator = self.rotator
        self.Bind(wx.EVT_MOTION, self.GetEndPos)

    def GetEndPos(self, event):
        if event.Dragging():  # Only when Dragging do the next step
            self.endPos = event.Position
            if event.LeftIsDown():  # When left is down, mov x and y
                self.movVector = self.endPos - self.startPos
                # here is the space for send self.movVector to motor or to calibrate
                if self.calibrateFlage is True:
                    self.rotator = self.startrotator + self.movVector[0] / 50
                    self.calibrateDialog.rotatorTextEntry.SetValue("{}".format(self.rotator))
                else:
                    try:
                        x = self.motorPos["X"] - self.movVector[0] * self.standard
                        y = self.motorPos["Y"] + self.movVector[1] * self.standard
                        self.gcs.MOV({"X": x,
                                      "Y": y})
                        # wait hexpod move to position
                        logger.info("gcs move x:{},y:{}".format(x, y))
                    except GCSError as gcserror:
                        ShowGCSErrorMessage(gcserror)
                        logger.error("gcs failed to move because:{}".format(gcserror))
            elif event.MiddleIsDown():  # When middle is down, mov z with a Z speed
                self.ZmovSpeed = self.startPos[1] - self.endPos[1]
                # here is the space for send self.ZmovSpeed to motor
                try:
                    z = self.ZmovSpeed * 0.001
                    self.gcs.MVR("Z", z)
                    logger.info("gcs move z:{}".format(z))
                except GCSError as gcserror:
                    ShowGCSErrorMessage(gcserror)
                    logger.error("gcs faied to move because:{}".format(gcserror))

    def UnbindMotionEvent(self, event):
        # Unbind the motion event for saving resource. Need more test to find if it  work.
        if not (event.MiddleUp() and event.LeftUp()):
            self.Unbind(wx.EVT_MOTION, handler=self.GetEndPos)

    # When double click mouse left, you get self.movVetor and send to motor or calibrate
    def MovetoPoint(self, event):
        height, width = self.ClientSize
        self.startPos = (height / 2, width / 2)
        self.endPos = event.Position
        self.movVector = self.endPos - self.startPos
        # here is the space for send self.movVector to motor or calibrate
        if self.calibrateFlage is True:
            movpos = self.pos + event.Position - [height / 2, width / 2]
            if movpos.x > 0 and movpos.y > 0:
                self.pos = movpos
                self.calibrateDialog.xoffsetTextEntry.SetValue("{}".format(movpos[0]))
                self.calibrateDialog.yoffsetTextEntry.SetValue("{}".format(movpos[1]))
        elif self.standardizationFlag is True:
            if len(self.standardpoints) < 1:
                self.standardpoints.append(event.Position)
            else:
                self.standardpoints.append(event.Position)
                point2 = self.standardpoints.pop()
                point1 = self.standardpoints.pop()
                # according to two point distance: distance = ((x1-x2)^2+(y1-y2)^2)^0.5.
                # Then dividend by 0.1mm will get you standard
                self.standard = 0.1 / ((point2.x - point1.x) ** 2 + (point2.y - point1.y) ** 2) ** 0.5
                print("standard is %f (mm/pixel)" % self.standard)
        else:
            try:
                x = self.movVector[0] * self.standard
                y = -self.movVector[1] * self.standard
                self.gcs.MVR({"X": x, "Y": y})
                logger.info("gcs move to x:{}, y:{}".format(x, y))
            except GCSError as gcserror:
                ShowGCSErrorMessage(gcserror)
                logger.error("gcs failed move to point because{}".format(gcserror))

    # When rotate mouse middle, you get self.Zmov
    def MoveZaxis(self, event):
        self.Zmov = event.GetWheelRotation() / event.GetWheelDelta()
        # Here is the space for sending self.Zmov to motor
        try:
            z = self.Zmov * 0.01
            self.gcs.MVR("Z", z)
            logger.info("gcs move z step:{}".format(z))
        except GCSError as gcserror:
            ShowGCSErrorMessage(gcserror)
            logger.error("gcs failed move z step because:{}".format(gcserror))

     # When calibrate button pressed, you can calibrate
    def Calibrate(self, event):
        if self.calibratButton.GetToggle():
            self.calibrateFlage = True
            # when you calibrate you can't standardization
            self.standardizationButton.Enable(False)
            self.calibrateDialog.rotatorTextEntry.SetValue("{}".format(self.rotator))
            self.calibrateDialog.expendChoice.SetSelection(self.expend - 1)
            self.calibrateDialog.xoffsetTextEntry.SetValue("{}".format(self.pos[0]))
            self.calibrateDialog.yoffsetTextEntry.SetValue("{}".format(self.pos[1]))
            logger.info("start calibrate")
            self.calibrateDialog.Show()
        else:
            self.calibrateFlage = False
            self.standardizationButton.Enable(enable=True)
            self.calibrateDialog.Hide()

    def Standardization(self, event):
        if self.standardizationButton.GetToggle():
            self.standardizationFlag = True
            # When standardization button pressed, you can standardization
            self.calibratButton.Enable(False)
        else:
            self.standardizationFlag = False
            self.calibratButton.Enable(enable=True)
            # dumped calibrated data
            file = open(".\\data\\{}mainCameraStandardization.pkl".format(self.username), "wb+")
            pickle.dump(self.standard, file, 4)
            logger.info("successfully standardization, standar is {}".format(self.standard))
            file.close()

     # When home Button pressed, hexpod will go home which set by SetHome button
    def GoHome(self, event):
        try:
            self.gcs.MOV(self.home)
            logger.info("successfully go home:{}".format(self.home))
            # wait for hexpod go home
        except GCSError as gcserror:
            logger.error("failed go home because:{}".format(gcserror))
            ShowGCSErrorMessage(gcserror)

    def SetHome(self, event):
        try:
            self.home = self.gcs.qPOS(["X", "Y", "Z"])
            file = open(".\\data\\{}home.pkl".format(self.username), "wb+")
            pickle.dump(self.home, file, 4)
            file.close()
            logger.info("successfully set home:{}".format(self.home))
        except GCSError as gcserror:
            logger.error("failed set home because:{}".format(gcserror))
            ShowGCSErrorMessage(gcserror)

    # When laser pulse process button pressed, hexpod will go back focus plan, trigger laser, and goback visual plan
    def LaserSpotTrigger(self, event):
        laserPulseThread = threading.Thread(target=self.LaserSpotTriggerThread)
        self.laserSpotTriggerButton.Disable()
        laserPulseThread.start()

    def LaserSpotTriggerThread(self):
        try:
            logger.info("try to do a laser spot trigger process")
            # open laser set dialog, if haven't
            if not self.setLaserButton.GetToggle():
                self.setLaserButton.SetToggle(True)
                self.setLaserDialog.Show()
            # set laser parameter
            self.setLaserDialog.SetLaserParameter()
            # set burst mode to trigger, if it is not
            if self.setLaserDialog.GetModeContinueOrTrigger() != "Trigger":
                self.setLaserDialog.SetModeTrigger()
            # check if laser is running, if not start running
            if self.setLaserDialog.GetPowerState() != "Run":
                self.setLaserDialog.LaserRun()
            # go to the focus Plane
            self.gcs.MOV(self.focusPlan)
            # wait on target
            pitools.waitontarget(self.gcs)
            logger.info("successfully go to focus plan:{}".format(self.focusPlan))
            # trigger laser
            self.setLaserDialog.SetModeTrigger()
            # wait trigger start
            time.sleep(0.2)
            # wait trigger finish
            while self.setLaserDialog.GetBurstToGo() != "0.0":
                time.sleep(0.2)
            logger.info("sucessfully go all burst pulse")
            # go back to visual plan
            self.gcs.MOV(self.visualPlan)
            pitools.waitontarget(self.gcs)
            logger.info("successfully do a laser spot trigger process")
        except Exception as ex:
            logger.error("failed do a laser spot trigger process because:{}".format(ex))
            ShowErrorMessage("failed do a laser spot trigger process because:{}".format(ex))
        finally:
            self.laserSpotTriggerButton.Enable(True)
            self.laserSpotTriggerButton.SetToggle(False)

    def SetFocusPlane(self, event):
        if self.setFocusPlaneButton.GetToggle():
            self.setFocusPlanDialog.visualPlanTextEntry.SetValue("{}".format(self.visualPlan["Z"]))
            self.setFocusPlanDialog.focusPlanTextEntry.SetValue("{}".format(self.focusPlan["Z"]))
            self.setFocusPlanDialog.Show()
        else:
            self.setFocusPlanDialog.Hide()

    # When step move pressed, main frame will show step move frame
    def StepMove(self, event):
        if self.stepMoveButton.GetToggle():
            self.stepMoveDialog.Show()
        else:
            self.stepMoveDialog.Hide()

    # When circle button pressed, it will show circle dialog
    def Circle(self, event):
        if self.circleButton.GetToggle():
            self.circleDialog.Show()
        else:
            self.circleDialog.Hide()

    def SetLaser(self, event):
        if self.setLaserButton.GetToggle():
            self.setLaserDialog.Show()
        else:
            self.setLaserDialog.Hide()

    # When find focus plan pressed, main frame will show find focus plan frame
    def AutoFindFocusePlan(self, event):
        if self.findFocusPlaneButton.GetToggle():
            self.findFocusPlaneDialog.Show()
        else:
            self.findFocusPlaneDialog.Hide()

    def ZigZagProcess(self, event):
        if self.zigZagButton.GetToggle():
            self.zigZagDialog.Show()
        else:
            self.zigZagDialog.Hide()

    def ShowOneFrame(self):
        self.bitmap = wx.Bitmap.FromBuffer(self.height, self.width, self.frame * 1)
        bufferedDC = wx.BufferedDC(self.clientDC, self.bitmap)
        self.DrawCorssHair(bufferedDC)
        bufferedDC.Destroy()

    # After show image from Camera, it will draw cross hairs with scale
    def DrawCorssHair(self, DC):
        # set pen
        DC.SetPen(wx.Pen("Red", width=2))
        # draw cross hair
        width, height = self.GetClientSize()
        DC.DrawLine(0, height / 2, width, height / 2)
        DC.DrawLine(width / 2, 0, width / 2, height)
        # a scale equale 10 um
        scale = self.scale * 0.001 / self.standard
        if self.DrawCorssHairFlag:
            for i in range(int(self.scaleRange / self.scale + 1)):
                if (i % 5) != 0 and i != 0:
                    DC.DrawLine((width / 2 - i * scale), (height / 2 - 5),
                                (width / 2 - i * scale), (height / 2 + 5))
                    DC.DrawLine((width / 2 + i * scale), (height / 2 - 5),
                                (width / 2 + i * scale), (height / 2 + 5))
                elif i != 0:
                    DC.DrawLine((width / 2 - i * scale), (height / 2 - 10),
                                (width / 2 - i * scale), (height / 2 + 10))
                    DC.DrawText("{}um".format(-i * self.scale), (width / 2 - i * scale), (height / 2 - 30))
                    DC.DrawLine((width / 2 + i * scale), (height / 2 - 10),
                                (width / 2 + i * scale), (height / 2 + 10))
                    DC.DrawText("{}um".format(i * self.scale), (width / 2 + i * scale),
                                (height / 2 - 30))
            for i in range(int(self.scaleRange / self.scale / 2 + 1)):
                if (i % 5) != 0 and i != 0:
                    DC.DrawLine((width / 2 - 5), (height / 2 - i * scale),
                                (width / 2 + 5), (height / 2 - i * scale))
                    DC.DrawLine((width / 2 - 5), (height / 2 + i * scale),
                                (width / 2 + 5), (height / 2 + i * scale))
                elif i != 0:
                    DC.DrawLine((width / 2 - 10), (height / 2 - i * scale),
                                (width / 2 + 10), (height / 2 - i * scale))
                    DC.DrawText("{}um".format(-i * self.scale), (width / 2 - 50), (height / 2 - i * scale))
                    DC.DrawLine((width / 2 - 10), (height / 2 + i * scale),
                                (width / 2 + 10), (height / 2 + i * scale))
                    DC.DrawText("{}um".format(i * self.scale), (width / 2 - 50), (height / 2 + i * scale))

    # a Input Dialog is standard dialog class used to be hierarchy
    class InputDialog(wx.Dialog):

        def __init__(self, *args, **kwargs):
            super(MainCameraPanel.InputDialog, self).__init__(*args, **kwargs, pos=(900, 500),
                                                              style=wx.CAPTION | wx.CLOSE_BOX | wx.STAY_ON_TOP)
            # add item
            # add sizer
            # bind function
            self.Bind(wx.EVT_CLOSE, self.OnClose)

        def OnClose(self, event):
            self.Hide()

    class StepMoveDialog(InputDialog):

        def __init__(self, parent):
            self.parent = parent
            super(MainCameraPanel.StepMoveDialog, self).__init__(parent=self.parent, title="Step move")
            # add item
            self.xStepSizeText = wx.StaticText(parent=self, label="X step size:")
            self.xStepSizeTextEntry = wx.TextCtrl(parent=self, value="0")
            self.yStepSizeText = wx.StaticText(parent=self, label="Y step size:")
            self.yStepSizeTextEntry = wx.TextCtrl(parent=self, value="0")
            self.zStepSizeText = wx.StaticText(parent=self, label="Z step size:")
            self.zStepSizeTextEntry = wx.TextCtrl(parent=self, value="0")
            self.xunit = wx.StaticText(parent=self, label="um")
            self.yunit = wx.StaticText(parent=self, label="um")
            self.zunit = wx.StaticText(parent=self, label="um")
            self.returnToLastStep = wx.Button(parent=self, label="Return to last step")
            self.stepInAllAxisesButton = wx.Button(parent=self, label="Step in all axises")
            self.goToPointButton = wx.Button(parent=self, label="Go to the point")
            bmp = wx.ArtProvider.GetBitmap(id=wx.ART_GO_BACK, client=wx.ART_BUTTON, size=(20, 20))
            self.xleftStepButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.yleftStepButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.zleftStepButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            bmp = wx.ArtProvider.GetBitmap(id=wx.ART_GO_FORWARD, client=wx.ART_BUTTON, size=(20, 20))
            self.xrightStepButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.yrightStepButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.zrightStepButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            # add sizer
            self.gridSizer = wx.FlexGridSizer(cols=5, vgap=10, hgap=1)
            self.staticTextSizeFlag = wx.SizerFlags(0)
            self.staticTextSizeFlag.Border(wx.LEFT, 60).Align(wx.Bottom)
            self.sizerFlag = wx.SizerFlags(0)
            self.gridSizer.AddMany([(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (self.xStepSizeText, self.staticTextSizeFlag),
                                    (self.xStepSizeTextEntry, self.sizerFlag),
                                    (self.xunit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.xleftStepButton, 0, wx.ALIGN_LEFT, 0),
                                    (self.xrightStepButton, 0, wx.ALIGN_RIGHT, 0),
                                    (self.yStepSizeText, self.staticTextSizeFlag),
                                    (self.yStepSizeTextEntry, self.sizerFlag),
                                    (self.yunit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.yleftStepButton, 0, wx.ALIGN_LEFT, 0),
                                    (self.yrightStepButton, 0, wx.ALIGN_RIGHT, 0),
                                    (self.zStepSizeText, self.staticTextSizeFlag),
                                    (self.zStepSizeTextEntry, self.sizerFlag),
                                    (self.zunit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.zleftStepButton, 0, wx.ALIGN_LEFT, 0),
                                    (self.zrightStepButton, 0, wx.ALIGN_RIGHT, 0),
                                    ])
            self.SetSizer(self.gridSizer)
            self.gridSizer.SetSizeHints(self)
            self.returnToLastStep.SetPosition((self.zStepSizeText.GetPosition() + [25 - 60, 40]))
            self.stepInAllAxisesButton.SetPosition((self.returnToLastStep.GetPosition() + [150, 0]))
            self.goToPointButton.SetPosition(self.stepInAllAxisesButton.GetPosition() + [150, 0])
            self.SetSize(self.GetClientSize() + [50 + 80, 100])
            # bind function
            self.Bind(wx.EVT_BUTTON, self.StepInAllAxises, self.stepInAllAxisesButton)
            self.Bind(wx.EVT_BUTTON, self.ReturnToLastStep, self.returnToLastStep)
            self.Bind(wx.EVT_BUTTON, self.OnStep, self.xleftStepButton)
            self.Bind(wx.EVT_BUTTON, self.OnStep, self.xrightStepButton)
            self.Bind(wx.EVT_BUTTON, self.OnStep, self.yleftStepButton)
            self.Bind(wx.EVT_BUTTON, self.OnStep, self.yrightStepButton)
            self.Bind(wx.EVT_BUTTON, self.OnStep, self.zleftStepButton)
            self.Bind(wx.EVT_BUTTON, self.OnStep, self.zrightStepButton)
            self.Bind(wx.EVT_BUTTON, self.GoToPoint, self.goToPointButton)
            # creat postion history
            self.postionHistory = []
            self.postionHistory.append(self.parent.gcs.qPOS())

        def StepInAllAxises(self, event):
            # if text entry is empty, set default value 0
            if not self.xStepSizeTextEntry.IsEmpty():
                x = float(self.xStepSizeTextEntry.GetValue())
            else:
                x = 0
            if not self.yStepSizeTextEntry.IsEmpty():
                y = float(self.yStepSizeTextEntry.GetValue())
            else:
                y = 0
            if not self.zStepSizeTextEntry.IsEmpty():
                z = float(self.zStepSizeTextEntry.GetValue())
            else:
                z = 0
            self.postionHistory.append(self.parent.gcs.qPOS())
            try:
                # try move and record postion
                x = x / 1000
                y = y / 1000
                z = z / 1000
                self.parent.gcs.MVR({"X": x, "Y": y, "Z": z})
                logger.info("successfully step in all axises, x:{}, y:{}, z:{}".format(x, y, z))
            except GCSError as gcserror:
                logger.error("failed step in all axises because:{}".format(gcserror))
                ShowGCSErrorMessage(gcserror)
                self.postionHistory.pop()

        def ReturnToLastStep(self, event):
            try:
                step = self.postionHistory.pop()
                self.parent.gcs.MOV()
                logger.info("sucessfully return to last step:{}".format(step))
            except GCSError as gcserror:
                logger.error("failed return to last step:{} because:{}".format(step, gcserror))
                ShowGCSErrorMessage(gcserror)
            except IndexError as indexerror:
                pass

        def OnStep(self, event):
            buttonlist = [self.xleftStepButton, self.xrightStepButton, self.yleftStepButton, self.yrightStepButton,
                          self.zleftStepButton, self.zrightStepButton]
            a = buttonlist.index(event.GetButtonObj())
            x = 0
            y = 0
            z = 0
            if a == 0:
                x = -float(self.xStepSizeTextEntry.GetValue())
            elif a == 1:
                x = float(self.xStepSizeTextEntry.GetValue())
            elif a == 2:
                y = -float(self.yStepSizeTextEntry.GetValue())
            elif a == 3:
                y = float(self.yStepSizeTextEntry.GetValue())
            elif a == 4:
                z = -float(self.zStepSizeTextEntry.GetValue())
            elif a == 5:
                z = float(self.zStepSizeTextEntry.GetValue())
            self.postionHistory.append(self.parent.gcs.qPOS())
            try:
                # try move and record postion
                x = x / 1000
                y = y / 1000
                z = z / 1000
                self.parent.gcs.MVR({"X": x, "Y": y, "Z": z})
                logger.info("sucessfully move one step, x:{}, y:{}, z:{}".format(x, y, z))
            except GCSError as gcserror:
                logger.error("failed move one step because:{}".format(gcserror))
                ShowGCSErrorMessage(gcserror)
                self.postionHistory.pop()

        def GoToPoint(self, event):
            # if text entry is empty, set default value 0
            if not self.xStepSizeTextEntry.IsEmpty():
                x = float(self.xStepSizeTextEntry.GetValue())
            else:
                x = 0
            if not self.yStepSizeTextEntry.IsEmpty():
                y = float(self.yStepSizeTextEntry.GetValue())
            else:
                y = 0
            if not self.zStepSizeTextEntry.IsEmpty():
                z = float(self.zStepSizeTextEntry.GetValue())
            else:
                z = 0
            self.postionHistory.append(self.parent.gcs.qPOS())
            try:
                # try move and record postion
                x = x / 1000
                y = y / 1000
                z = z / 1000
                self.parent.gcs.MOV({"X": x, "Y": y, "Z": z})
                logger.error("successfully move to point, x:{}, y:{}, z:{}".format(x, y, z))
            except GCSError as gcserror:
                logger.error("failed move to point because:{}".format(gcserror))
                ShowGCSErrorMessage(gcserror)
                self.postionHistory.pop()

        def OnClose(self, event):
            self.Hide()
            self.Parent.stepMoveButton.SetToggle(False)

    class CircleDialog(InputDialog):

        def __init__(self, parent):
            self.parent = parent
            super(MainCameraPanel.CircleDialog, self).__init__(parent=self.parent, title="Circle", size=[760, 550])
            # add item
            self.rMinText = wx.StaticText(parent=self, label="min Radius ")
            self.rMinTextEntry = wx.TextCtrl(parent=self, value="0")
            self.rMinUnit = wx.StaticText(parent=self, label="mm")
            self.rMaxText = wx.StaticText(parent=self, label="max Radius ")
            self.rMaxTextEntry = wx.TextCtrl(parent=self, value="0.03")
            self.rMaxUnit = wx.StaticText(parent=self, label="mm")
            self.distanceBetweenTwoWavePointText = wx.StaticText(parent=self, label="Distance between \n"
                                                                                    "two wave point :")
            self.distanceBetweenTwoWavePointTextEntry = wx.TextCtrl(parent=self, value="0.0003")
            self.distanceBetweenTwoWavePointUnit = wx.StaticText(parent=self, label="mm")
            self.numberOfTurnsText = wx.StaticText(parent=self, label="Number of turns ")
            self.numberOfTurnsTextEntry = wx.TextCtrl(parent=self, value="70")
            self.zAxisStepSizeText = wx.StaticText(parent=self, label="Z axis step space")
            self.zAxisStepSizeTextEntry = wx.TextCtrl(parent=self, value="0.01")
            self.zAxisStepSizeUnit = wx.StaticText(parent=self, label="mm")
            self.zAxisStepTimeText = wx.StaticText(parent=self, label="Z axis step number ")
            self.zAxisStepTimeTextEntry = wx.TextCtrl(parent=self, value="10")
            self.columsSpaceText = wx.StaticText(parent=self, label="Columns space")
            self.columsSpaceTextEntry = wx.TextCtrl(parent=self, value="0.1")
            self.columsSpaceUnit = wx.StaticText(parent=self, label="mm")
            self.columsNumberText = wx.StaticText(parent=self, label="Colums number ")
            self.columsNumberTextEntry = wx.TextCtrl(parent=self, value="1")
            self.rowsSpaceText = wx.StaticText(parent=self, label="Rows space")
            self.rowsSpaceTextEntry = wx.TextCtrl(parent=self, value="0.1")
            self.rowsSpaceUnit = wx.StaticText(parent=self, label="mm")
            self.rowsNumberText = wx.StaticText(parent=self, label="Rows number ")
            self.rowsNumberTextEntry = wx.TextCtrl(parent=self, value="1")
            self.WTRText = wx.StaticText(parent=self, label="Wave rate")
            self.WTRTextEntry = wx.TextCtrl(parent=self, value="20")
            self.viewCircleButton = wx.Button(parent=self, label="View the Circle")
            self.viewCirclePanel = wxmplot.PlotPanel(parent=self, size=(450, 450), pos=(310, 0),
                                                     show_config_popup=False)
            self.viewCirclePanel.plot(xdata=np.array([0, ]), ydata=np.array([0, ]), xlabel="X/mm", ylabel="Y/mm")
            self.runButton = wx.Button(parent=self, label="Run", size=self.viewCircleButton.GetSize())
            self.zMoveStyleText = wx.StaticText(parent=self, label="z axis move style")
            self.zMoveStyleChoice = wx.Choice(parent=self, choices=["Step", "Synchrony"],
                                              size=self.rMinTextEntry.GetSize())
            self.zMoveStyleChoice.SetSelection(0)
            # add statusBar
            self.statusBar = wx.StatusBar(parent=self)
            self.statusBar.SetPosition((0, 490))
            self.statusBar.SetSize((760, 25))
            self.statusBar.SetStatusText(text="ready")
            # add sizer
            self.gridSizer = wx.FlexGridSizer(cols=3, vgap=10, hgap=1)
            self.staticTextSizeFlag = wx.SizerFlags(1)
            self.staticTextSizeFlag.Border(wx.LEFT, 10).Align(wx.Bottom)
            self.sizerFlag = wx.SizerFlags(1)
            self.gridSizer.AddMany([(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (self.rMinText, self.staticTextSizeFlag),
                                    (self.rMinTextEntry, self.sizerFlag),
                                    (self.rMinUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.rMaxText, self.staticTextSizeFlag),
                                    (self.rMaxTextEntry, self.sizerFlag),
                                    (self.rMaxUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.distanceBetweenTwoWavePointText, self.staticTextSizeFlag),
                                    (self.distanceBetweenTwoWavePointTextEntry, self.sizerFlag),
                                    (self.distanceBetweenTwoWavePointUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.numberOfTurnsText, self.staticTextSizeFlag),
                                    (self.numberOfTurnsTextEntry, self.sizerFlag),
                                    (0, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.zAxisStepSizeText, self.staticTextSizeFlag),
                                    (self.zAxisStepSizeTextEntry, self.sizerFlag),
                                    (self.zAxisStepSizeUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.zAxisStepTimeText, self.staticTextSizeFlag),
                                    (self.zAxisStepTimeTextEntry, self.sizerFlag), (0, 0, 0, 0),
                                    (self.zMoveStyleText, self.staticTextSizeFlag),
                                    (self.zMoveStyleChoice, self.sizerFlag), (0, 0, 0, 0),
                                    (self.columsSpaceText, self.staticTextSizeFlag),
                                    (self.columsSpaceTextEntry, self.sizerFlag),
                                    (self.columsSpaceUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.columsNumberText, self.staticTextSizeFlag),
                                    (self.columsNumberTextEntry, self.sizerFlag), (0, 0, 0, 0),
                                    (self.rowsSpaceText, self.staticTextSizeFlag),
                                    (self.rowsSpaceTextEntry, self.sizerFlag),
                                    (self.rowsSpaceUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.rowsNumberText, self.staticTextSizeFlag),
                                    (self.rowsNumberTextEntry, self.sizerFlag), (0, 0, 0, 0),
                                    (self.WTRText, self.staticTextSizeFlag),
                                    (self.WTRTextEntry, self.sizerFlag), (0, 0, 0, 0),
                                    (self.viewCircleButton, self.staticTextSizeFlag),
                                    (self.runButton, self.staticTextSizeFlag),
                                    (0, 0, 0, 0)
                                    ])
            self.SetSizer(self.gridSizer)
            # bind function
            self.Bind(wx.EVT_BUTTON, self.ViewOrRun, self.viewCircleButton)
            self.Bind(wx.EVT_BUTTON, self.ViewOrRun, self.runButton)
            self.Bind(wx.EVT_CLOSE, self.OnClose)
            # set circle properties
            self.rMin = float(0)
            self.rMax = float(0)
            self.distance = float(0)
            self.numberOfTurns = float(0)
            self.zStepSize = float(0)
            self.zStepNumber = int(0)
            self.WTR = 10
            self.focusPlan = {"Z": 0}
            self.startPosition = {"X": None, "Y": None}
            self.Center()

        def ViewOrRun(self, event):
            self.runButton.Disable()
            self.viewCircleButton.Disable()
            # read value from dialog
            rMin = float(self.rMinTextEntry.GetValue())
            rMax = float(self.rMaxTextEntry.GetValue())
            distance = float(self.distanceBetweenTwoWavePointTextEntry.GetValue())
            numberOfTurns = float(self.numberOfTurnsTextEntry.GetValue())
            WTR = int(self.WTRTextEntry.GetValue())
            # check WTR is not out of range
            if WTR < 10 or WTR > 1000:
                wx.MessageDialog.ShowModal(wx.MessageDialog(parent=None,
                                                            message="wave rate range is (10,1000), out of limit",
                                                            caption="Error",
                                                            style=wx.OK))
                self.viewCircleButton.Enable()
                self.runButton.Enable()
                return
            # if circle properties have be changed, circle should be calc and send to controller
            if (rMin != self.rMin) \
                    or (rMax != self.rMax) \
                    or (distance != self.distance) \
                    or (numberOfTurns != self.numberOfTurns):
                # set status bar and log status
                self.statusBar.SetStatusText("Calculating wave points")
                logger.info("calculating wave points")
                logger.info("wave parameter:rMin{}; rMax{}; distance{}; numberOfTurns{};"
                            .format(rMin, rMax, distance, numberOfTurns))
                pi = 3.141592654
                b = (rMax - rMin) / (2 * pi * numberOfTurns)
                # set parameter for calc
                r = rMin
                # add rMin round
                # X and Y list used to save point coordinate
                self.xList = np.array([])
                self.yList = np.array([])
                theta = 0
                while theta < 2 * pi:
                    self.xList = np.append(self.xList, rMin * np.cos(theta))
                    self.yList = np.append(self.yList, rMin * np.sin(theta))
                    theta = theta + distance / np.sqrt((b ** 2 + r ** 2))
                # add forward period spiral round
                theta = 0
                while theta < 2 * pi * numberOfTurns:
                    r = rMin + b * theta
                    self.xList = np.append(self.xList, r * np.cos(theta))
                    self.yList = np.append(self.yList, r * np.sin(theta))
                    theta = theta + distance / np.sqrt((b ** 2 + r ** 2))
                # add rMax round
                theta = 0
                while theta < 2 * pi:
                    self.xList = np.append(self.xList, rMax * np.cos(theta))
                    self.yList = np.append(self.yList, rMax * np.sin(theta))
                    theta = theta + distance / np.sqrt((b ** 2 + r ** 2))
                # add backforwad period spiral round
                theta = 0
                while theta < 2 * pi * numberOfTurns:
                    r = rMax - b * theta
                    self.xList = np.append(self.xList, r * np.cos(theta))
                    self.yList = np.append(self.yList, r * np.sin(theta))
                    theta = theta + distance / np.sqrt((b ** 2 + r ** 2))
            # else it is considered that wave generator has already been set successfully, and will do nothing
                # if view button pressed, it retrive data from wave table, and display it on view panel
                # if data is successfully transferred, save properties
                self.rMin = rMin
                self.rMax = rMax
                self.distance = distance
                self.numberOfTurns = numberOfTurns
                # plot data on view panel
                self.statusBar.SetStatusText("plotting")
                self.viewCirclePanel.plot(self.xList, self.yList,
                                          xlabel="X/mm", ylabel="Y/mm",
                                          marker='o',
                                          xmin=-1.01 * rMax, xmax=1.01 * rMax,
                                          ymin=-1.01 * rMax, ymax=1.01 * rMax,
                                          )
            # if view button pressed, plot and quit
            if event.GetEventObject() == self.viewCircleButton:
                # if only view button pressed, method will exit here
                wx.MessageDialog.ShowModal(wx.MessageDialog(parent=None,
                                                            message="wave points has been plot",
                                                            caption="Information",
                                                            style=wx.OK))
                self.viewCircleButton.Enable()
                self.runButton.Enable()
                self.statusBar.SetStatusText("ready")
            # if run button pressed, run runThread and wait
            if event.GetEventObject() == self.runButton:
                self.runThread = threading.Thread(target=self.RunThread, args=(rMin, rMax, distance, numberOfTurns))
                # set thread stop flage. if stop Flage is True, it will quit loop
                self.runThread.stopFlage = False
                self.runThread.start()

        def RunThread(self, rMin, rMax, distance, numberOfTurns):
            self.parent.laserSpotTriggerButton.Disable()
            self.parent.findFocusPlaneDialog.startButton.Disable()
            self.parent.zigZagDialog.startButton.Disable()
            # while run button preesed, it will start run thread
            zStepSize = float(self.zAxisStepSizeTextEntry.GetValue())
            zStepNumber = int(self.zAxisStepTimeTextEntry.GetValue())
            colSpace = float(self.columsSpaceTextEntry.GetValue())
            colNumber = int(self.columsNumberTextEntry.GetValue())
            rowSpace = float(self.rowsSpaceTextEntry.GetValue())
            rowNumber = int(self.rowsNumberTextEntry.GetValue())
            startPos = self.parent.gcs.qPOS(["X", "Y"])
            startPos.setdefault("Z", self.parent.visualPlan["Z"])
            WTR = int(self.WTRTextEntry.GetValue())
            style = self.zMoveStyleChoice.GetSelection()
            logger.info("start run circle thread, parameter:\n"
                        "zStepSize:{}, zStepNumber:{}, colSpace:{}, colNumber:{}, rowSpace:{}, rowNumber:{}, "
                        "startPos:{}, WTR:{}, style:{}".format(zStepSize, zStepNumber, colSpace, colNumber, rowSpace,
                                                               rowNumber, startPos, WTR, style))
            # if set laser dialog haven't show, show it
            if not self.parent.setLaserButton.GetToggle():
                self.parent.setLaserButton.SetToggle(True)
                self.parent.setLaserDialog.Show()
            # check if laser is power on, if not power it on
            if self.parent.setLaserDialog.GetPowerState() != "PowerOn":
                self.parent.setLaserDialog.PowerOn()
            if style == 0:
                try:
                    # send first round data to wave table 1 and 2, and connect them
                    self.statusBar.SetStatusText(
                        "Sending data, estimated time:{}s".format(int(self.xList.shape[0] * 2 / 400)))
                    self.SendWaveData(0, 0, colSpace, rowSpace, rowNumber, startPos)
                    # set all wave generators parameter
                    self.parent.gcs.WGC({1: 1, 2: 1})
                    self.parent.gcs.WSL(1, 1)
                    self.parent.gcs.WSL(2, 2)
                    self.parent.gcs.WTR([1, 2], [WTR, WTR], [1, 1])
                    for i in range(0, colNumber):
                        for j in range(0, rowNumber):
                            # wirte wave points.
                            # when even rounds connect table 1 and 2. when odds rounds connect table 3 and 4
                            if j < rowNumber - 1:
                                sendWaveDataThread = threading.Thread(target=self.SendWaveData, args=(i, j + 1,
                                                                                                      colSpace,
                                                                                                      rowSpace,
                                                                                                      rowNumber,
                                                                                                      startPos))
                            else:
                                sendWaveDataThread = threading.Thread(target=self.SendWaveData, args=(i + 1, 0,
                                                                                                      colSpace,
                                                                                                      rowSpace,
                                                                                                      rowNumber,
                                                                                                      startPos))
                            sendWaveDataThread.setDaemon(True)
                            sendWaveDataThread.start()
                            # set start position
                            for k in range(0, zStepNumber):
                                # if stop button not pressed and stop flage has been set, wave generator can be start
                                if not self.runThread.stopFlage:
                                    x = startPos["X"] + i * colSpace + rMin
                                    y = startPos["Y"] + j * rowSpace
                                    z = self.parent.focusPlan["Z"] + k * zStepSize
                                    self.statusBar.SetStatusText("Move to the start point")
                                    logger.info("move to the start point, x:{}, y:{}, z:{}".format(x, y, z))
                                    self.parent.gcs.MOV({"X": x,
                                                         "Y": y,
                                                         "Z": z})
                                    pitools.waitontarget(self.parent.gcs)
                                    self.statusBar.SetStatusText("Running...")
                                    self.parent.setLaserDialog.ContinueRun()
                                    logger.info("start running wave generator")
                                    self.parent.gcs.WGO({1: 1, 2: 1})
                                while True in self.parent.gcs.qWGO([1, 2]).values():
                                    # if stop button pressed and stop flage has been set, stop and rasie error
                                    if self.runThread.stopFlage:
                                        self.parent.setLaserDialog.Pause()
                                        self.statusBar.SetStatusText("STOP!!")
                                        logger.info("wave generator has been stopped")
                                        self.parent.gcs.HLT(axes=["X", "Y", "Z", "U", "V", "W"], noraise=True)
                                        self.parent.gcs.WGO({1: 0, 2: 0})
                                        sendWaveDataThread.join(1)
                                        raise Exception("STOP")
                                    else:
                                        time.sleep(0.2)
                                self.parent.setLaserDialog.Pause()
                                logger.info("successfully run wave generator one round")
                            sendWaveDataThread.join()
                            # connect wave tables.
                            # when even rounds connect table 1 and 2. when odds rounds connect table 3 and 4
                            self.parent.gcs.WSL(1, (i * rowNumber + j + 1) % 2 * 2 + 1)
                            self.parent.gcs.WSL(2, (i * rowNumber + j + 1) % 2 * 2 + 2)
                    self.parent.gcs.MOV(startPos)
                    wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None, message="finished", caption="Information", style=wx.OK))
                    self.statusBar.SetStatusText("ready")
                    logger.info("successfully run circles process")
                except Exception as exception:
                    logger.error("failed run circles process because:{}".format(exception))
                    wx.MessageDialog.ShowModal(wx.MessageDialog(parent=None, message="failed run because error:\n{}"
                                                                .format(exception), style=wx.OK))
                finally:
                    self.viewCircleButton.Enable()
                    self.runButton.Enable()
            else:
                if self.focusPlan is not self.parent.focusPlan or \
                        self.zStepNumber is not zStepNumber or \
                        self.zStepSize is not zStepSize or \
                        rMin is not self.rMin or \
                        rMax is not self.rMax or \
                        distance is not self.distance or \
                        numberOfTurns is not self.numberOfTurns or \
                        WTR is not self.WTR:
                    ### add z line to wave table 5. wave table 5 and 6 will be z axis table
                    # calc first step z wave point. z axis point will 1000 time leas than x and y
                    self.statusBar.SetStatusText("Calculating Z axis wave points")
                    logger.info("calculating Z axis wave points")
                    self.zList = np.arange(self.parent.focusPlan["Z"],
                                           self.parent.focusPlan["Z"] + zStepSize * zStepNumber,
                                           zStepSize / (self.xList.shape[0] * WTR / 1000))
                    # send z data to table 5
                    self.statusBar.SetStatusText("Sending Z axis wave points, estimated time:{}s"
                                                 .format(int(self.zList.shape[0] / 400)))
                    logger.info("start sending Z axis wave points, points size{}".format(self.zList.shape[0]))
                    pitools.writewavepoints(self.parent.gcs, 5, self.zList.tolist(), 100)
                    logger.info("Z axis wave points has been sent successfully")
                    # # save setting
                    self.zStepNumber = zStepNumber
                    self.zStepSize = zStepSize
                    self.focusPlan = self.parent.focusPlan
                    self.WTR = WTR
                try:
                    ### set all wave generators run cycles
                    # wavegenerator 1~2 saved x and y points spiral period, 3~4 for next circle, 5, 6 for z,
                    # 7~8 for ramp reserved. x and y cycle equals z step number, z cycle only once
                    self.parent.gcs.WGC({1: zStepNumber, 2: zStepNumber, 3: 1})
                    ### set all wave generators rate, with straight line interpol
                    # because data number in z axis is 10 time lower, so the wave rate should be 10 time higher
                    self.parent.gcs.WTR([1, 2, 3], [WTR, WTR, 1000], [1, 1, 1])
                    ### send first round data to wave table 1, 2 and ramp. method SendWaveData can add offset
                    self.statusBar.SetStatusText(
                        "Sending data, estimated time:{}s".format(int(self.xList.shape[0] * 2 / 400)))
                    self.SendWaveData(0, 0, colSpace, rowSpace, rowNumber, startPos)
                    # self.SendZAxisWaveData(0)
                    for i in range(0, colNumber):
                        for j in range(0, rowNumber):
                            if not self.runThread.stopFlage:
                                ### calc round befor ramp start for save time
                                xRoundNumber = (i * rowNumber + j) % 2 * 2 + 1
                                yRoundNumber = (i * rowNumber + j) % 2 * 2 + 2
                                k = 0
                                ### run the ramp which saved in wave table 5. only y axis need to move
                                # move to start position
                                x = startPos["X"] + i * colSpace + rMin
                                y = startPos["Y"] + j * rowSpace
                                z = self.focusPlan["Z"]
                                self.statusBar.SetStatusText("Move to the start point")
                                self.parent.gcs.MOV({"X": x,
                                                     "Y": y,
                                                     "Z": z})
                                pitools.waitontarget(self.parent.gcs)
                                logger.info("move to the start point, x:{}, y:{}, z:{}".format(x, y, z))
                                # when even rounds connect table 1 and 2. when odds rounds connect table 3 and 4
                                self.parent.gcs.WSL({1: xRoundNumber,
                                                     2: yRoundNumber,
                                                     3: 5})
                                self.statusBar.SetStatusText("Running...")
                                self.parent.setLaserDialog.ContinueRun()
                                logger.info("start running wave generator")
                                self.parent.gcs.WGO({1: 1, 2: 1, 3: 1})
                                ### wirte next points.
                                # if even rounds connect table 1 and 2. when odds rounds connect table 3 and 4
                                if j < rowNumber - 1:
                                    sendWaveDataThread = threading.Thread(target=self.SendWaveData, args=(i, j + 1,
                                                                                                          colSpace,
                                                                                                          rowSpace,
                                                                                                          rowNumber,
                                                                                                          startPos))
                                else:
                                    sendWaveDataThread = threading.Thread(target=self.SendWaveData, args=(i + 1, 0,
                                                                                                          colSpace,
                                                                                                          rowSpace,
                                                                                                          rowNumber,
                                                                                                          startPos))
                                    sendWaveDataThread.start()
                                    while True in self.parent.gcs.qWGO([1, 2, 3]).values():
                                        # if runThread stopFlage is set, stop instance and raise gcserror
                                        if self.runThread.stopFlage:
                                            self.parent.setLaserDialog.Pause()
                                            self.statusBar.SetStatusText("STOP!!")
                                            logger.info("wave generator has been stopped")
                                            self.parent.gcs.HLT(axes=["X", "Y", "Z", "U", "V", "W"], noraise=True)
                                            self.parent.gcs.WGO({1: 0, 2: 0, 3: 0})
                                            sendWaveDataThread.join(1)
                                            raise Exception("STOP")
                                        else:
                                            time.sleep(0.2)
                                    self.parent.setLaserDialog.Pause()
                                    logger.info("successfully run wave generator one round")
                                    # wait untill send wave data thread finished
                                    sendWaveDataThread.join()
                            else:
                                raise Exception("STOP")
                    self.parent.gcs.MOV(startPos)
                    wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None, message="finished", caption="Information", style=wx.OK))
                    self.statusBar.SetStatusText("ready")
                    logger.info("successfully run circles process")
                except Exception as exception:
                    logger.error("failed run circles process because:{}".format(exception))
                    wx.MessageDialog.ShowModal(wx.MessageDialog(parent=None, message="failed run because error:\n{}"
                                                                .format(exception), style=wx.OK))
                finally:
                    self.viewCircleButton.Enable()
                    self.runButton.Enable()
            self.parent.laserSpotTriggerButton.Enable()
            self.parent.findFocusPlaneDialog.startButton.Enable()
            self.parent.zigZagDialog.startButton.Enable()

        def OnClose(self, event):
            self.Hide()
            self.Parent.circleButton.SetToggle(False)

        def SendWaveData(self, i, j, colSpace, rowSpace, rowNumber, startPos):
            # send wave data function will as a thread target, will add offset and send wave data as motor move
            try:
                xOffset = startPos["X"] + i * colSpace
                yOffset = startPos["Y"] + j * rowSpace
                xList = self.xList + xOffset
                yList = self.yList + yOffset
                # yRamp = self.yRamp + yOffset
                self.parent.gcs.WCL((i * rowNumber + j) % 2 * 2 + 1)
                self.parent.gcs.WCL((i * rowNumber + j) % 2 * 2 + 2)
                # self.parent.gcs.WCL(5)
                # only when stop flage not set, can Send Wave Data process
                if not self.runThread.stopFlage:
                    logger.info("start sending X axis wave points, points size{}".format(xList.shape[0]))
                    pitools.writewavepoints(self.parent.gcs, (i * rowNumber + j) % 2 * 2 + 1, xList.tolist(), 100)
                    logger.info("X axis wave points has been sent successfully")
                if not self.runThread.stopFlage:
                    logger.info("start sending Y axis wave points, points size{}".format(yList.shape[0]))
                    pitools.writewavepoints(self.parent.gcs, (i * rowNumber + j) % 2 * 2 + 2, yList.tolist(), 100)
                    logger.info("Y axis wave points has been sent successfully")
            except GCSError as gcserror:
                logger.error("failed send wave data because:{}".format(gcserror))
                ShowGCSErrorMessage(gcserror)

    class QueryPostionWindow(wx.Window):

        def __init__(self, *args, **kw):
            super(MainCameraPanel.QueryPostionWindow, self).__init__(*args, **kw)
            self.posx = 0
            self.posy = 0
            self.posz = 0
            self.xpostionStaticText = wx.StaticText(parent=self, label="X :{}/mm".format(self.posx))
            self.ypostionStaticText = wx.StaticText(parent=self, label="Y :{}/mm".format(self.posy))
            self.zpostionStaticText = wx.StaticText(parent=self, label="Z :{}/mm".format(self.posz))
            self.boxSizer = wx.BoxSizer(wx.VERTICAL)
            self.sizeFlag = wx.SizerFlags(0)
            self.sizeFlag.Align(wx.Left)
            self.sizeFlag.Border(wx.BOTTOM | wx.TOP | wx.LEFT, 5)
            self.boxSizer.AddMany([(self.xpostionStaticText, self.sizeFlag), (self.ypostionStaticText, self.sizeFlag),
                                   (self.zpostionStaticText, self.sizeFlag)])
            self.SetSizer(self.boxSizer)

    class CalibrateDialog(InputDialog):

        def __init__(self, parent):
            self.parent = parent
            super(MainCameraPanel.CalibrateDialog, self).__init__(parent=self.parent, title="Calibrate set",
                                                                  size=(350, 260))
            # initialize property
            self.fileName = ".\\data\\{}mainCameraCalibrate.pkl".format(self.parent.username)
            # add items
            self.expendText = wx.StaticText(parent=self, label="Camera expend: ")
            self.expendChoice = wx.Choice(parent=self, choices=["1X", "2X"], size=(111, 25))
            self.expendChoice.SetSelection(1)
            self.rotatorText = wx.StaticText(parent=self, label="Camera rotate:")
            self.rotatorTextEntry = wx.TextCtrl(parent=self, value="{} ".format(self.parent.rotator),
                                                style=wx.TE_PROCESS_ENTER)
            self.xoffsetText = wx.StaticText(parent=self, label="Camera xoffset: ")
            self.xoffsetTextEntry = wx.TextCtrl(parent=self, value="0", style=wx.TE_PROCESS_ENTER)
            self.yoffsetText = wx.StaticText(parent=self, label="Camera yoffset: ")
            self.yoffsetTextEntry = wx.TextCtrl(parent=self, value="0", style=wx.TE_PROCESS_ENTER)
            self.loadCalibrateFileText = wx.StaticText(parent=self, label="Load from file")
            self.loadCalibrateFileNameText = wx.StaticText(parent=self, label="", size=(150, 25), pos=(175, 155),
                                                           style=wx.ST_ELLIPSIZE_START)
            self.loadCalibrateFileButton = wx.Button(parent=self, label="Load", size=(50, 26))
            self.staticLine = wx.StaticLine(parent=self)
            self.OKButton = wx.Button(parent=self, label="OK")
            self.cancelButton = wx.Button(parent=self, label="Cancel")
            # add sizer
            self.gridSizer = wx.FlexGridSizer(cols=2, vgap=10, hgap=1)
            self.staticTextSizeFlag = wx.SizerFlags(1)
            self.staticTextSizeFlag.Border(wx.LEFT, 10).Align(wx.Bottom)
            self.textEntrySizerFlag = wx.SizerFlags(1)
            self.gridSizer.AddMany([(0, 0, 0, 0), (0, 0, 0, 0),
                                    (self.expendText, self.staticTextSizeFlag),
                                    (self.expendChoice, self.textEntrySizerFlag),
                                    (self.rotatorText, self.staticTextSizeFlag),
                                    (self.rotatorTextEntry, self.textEntrySizerFlag),
                                    (self.xoffsetText, self.staticTextSizeFlag),
                                    (self.xoffsetTextEntry, self.textEntrySizerFlag),
                                    (self.yoffsetText, self.staticTextSizeFlag),
                                    (self.yoffsetTextEntry, self.textEntrySizerFlag),
                                    (self.loadCalibrateFileText, self.staticTextSizeFlag),
                                    (self.loadCalibrateFileButton, self.textEntrySizerFlag),
                                    ])
            self.SetSizer(self.gridSizer)
            self.staticLine.SetPosition((0, 182))
            self.staticLine.SetSize((350, 2))
            self.cancelButton.SetPosition((245, 189))
            self.OKButton.SetSize(88, 30)
            self.OKButton.SetPosition((146, 189))
            # Bind Event
            self.Bind(wx.EVT_BUTTON, self.LoadFile, self.loadCalibrateFileButton)
            self.Bind(wx.EVT_BUTTON, self.SetCalibration, self.OKButton)
            self.Bind(wx.EVT_BUTTON, self.OnClose, self.cancelButton)
            self.Bind(wx.EVT_TEXT_ENTER, self.SetCalibration)

        def LoadFile(self, event):
            self.fileName = wx.FileSelector(message="Load File", default_path=".\\data\\",
                                            wildcard="PKL files (*.pkl)|*.pkl",
                                            flags=wx.FD_OPEN)
            if self.fileName.strip():
                self.loadCalibrateFileNameText.SetLabel("{}".format(self.fileName))
                logger.info("load {}".format(self.fileName))
                if "CameraCalibrate.pkl" in self.fileName:
                    with open(self.fileName, "rb") as file:
                        try:
                            expend = pickle.load(file)
                            self.expendChoice.SetSelection(int(expend - 1))
                            rotator = pickle.load(file)
                            self.rotatorTextEntry.SetValue("{}".format(rotator))
                            pos = pickle.load(file)
                            self.xoffsetTextEntry.SetValue("{}".format(pos[0]))
                            self.yoffsetTextEntry.SetValue("{}".format(pos[1]))
                            logger.info("successfully load calibrate file:{}".format(self.fileName))
                        except Exception as ex:
                            logger.error("failed load calibrate file because:{}".format(ex))
                            wx.MessageDialog.ShowModal(
                                wx.MessageDialog(parent=None,
                                                 message="exception accured in reading :"
                                                         "\n{}".format(self.fileName),
                                                 style=wx.OK))
                else:
                    wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None,
                                         message="Need load a CameraCalibrate.pkl file.",
                                         style=wx.OK))

        def SetCalibration(self, event):
            expend = int(self.expendChoice.GetSelection() + 1)
            rotator = float(self.rotatorTextEntry.GetValue())
            pos = [int(self.xoffsetTextEntry.GetValue()), int(self.yoffsetTextEntry.GetValue())]
            self.parent.expend = expend
            self.parent.rotator = rotator
            self.parent.pos = pos
            if wx.MessageDialog.ShowModal(
                    wx.MessageDialog(parent=None,
                                     message="Want to Save to:"
                                             "\n{}".format(self.fileName),
                                     style=wx.YES_NO)) == wx.ID_YES:
                try:
                    with open(self.fileName, "wb+") as file:
                        pickle.dump(expend, file, 4)
                        pickle.dump(rotator, file, 4)
                        pickle.dump(pos, file, 4)
                        logger.info("sucessfully save calibrate file:{}\n"
                                    "expand:{}, rotater:{}, pos:{}".format(self.fileName, expend, rotator, pos))
                        self.OnClose(event=None)
                except Exception as ex:
                    logger.error("failed save calibrate file because:{}".format(ex))
                    wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None,
                                         message="Failed to save:"
                                                 "\n{}".format(self.fileName),
                                         style=wx.OK))

        def OnClose(self, event):
            self.Hide()
            self.parent.calibratButton.SetToggle(False)
            self.parent.Calibrate(None)

    class SetFocusPlanDialog(InputDialog):

        class TextCtrl(wx.TextCtrl):
            def __init__(self, uplimit=100, downlimit=0, diff=0.1, *args, **kwargs):
                super(wx.TextCtrl, self).__init__(*args, **kwargs)
                self.uplimit = uplimit
                self.downlimit = downlimit
                self.diff = diff
                self.Bind(wx.EVT_KEY_DOWN, self.AddNumber)

            def AddNumber(self, event):
                try:
                    event.keyCode = event.GetKeyCode()
                    if event.keyCode == 315 or event.keyCode == 317:
                        currentValue = float(self.GetValue())
                        if event.keyCode == 315:
                            currentValue = currentValue + self.diff
                        elif event.keyCode == 317:
                            currentValue = currentValue - self.diff
                        if self.downlimit <= currentValue <= self.uplimit:
                            self.SetValue(value="{}".format(round(currentValue, 3)))
                    else:
                        pass
                except Exception as ex:
                    ShowErrorMessage(ex)
                finally:
                    event.Skip()

        def __init__(self, parent):
            self.parent = parent
            super(MainCameraPanel.SetFocusPlanDialog, self).__init__(parent=self.parent, title="Set focus plan",
                                                                     size=(370, 220))
            # initialize property
            self.fileName = ".\\data\\{}focusPlan.pkl".format(self.parent.username)
            # add items
            self.visualPlanText = wx.StaticText(parent=self, label="Visual plan: ")
            self.visualPlanTextEntry = self.TextCtrl(uplimit=10, downlimit=-10, diff=0.001,
                                                     parent=self, value="0.000", style=wx.TE_PROCESS_ENTER)
            self.visualPlanUnit = wx.StaticText(parent=self, label="mm")
            self.focusPlanText = wx.StaticText(parent=self, label="Focus plan: ")
            self.focusPlanTextEntry = self.TextCtrl(uplimit=10, downlimit=-10, diff=0.001,
                                                    parent=self, value="0.000", style=wx.TE_PROCESS_ENTER)
            self.focusPlanUnit = wx.StaticText(parent=self, label="mm")
            bmp = wx.ArtProvider.GetBitmap(id=wx.ART_GO_UP, client=wx.ART_BUTTON, size=(20, 20))
            self.visualPlanStepUpButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.focusPlanStepUpButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            bmp = wx.ArtProvider.GetBitmap(id=wx.ART_GO_DOWN, client=wx.ART_BUTTON, size=(20, 20))
            self.visualPlanStepDownButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.focusPlanStepDownButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            bmp = wx.ArtProvider.GetBitmap(id=wx.ART_GOTO_FIRST, client=wx.ART_BUTTON, size=(20, 20))
            self.visualPlanGoButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.focusPlanGoButton = buttons.GenBitmapButton(parent=self, bitmap=bmp)
            self.loadCalibrateFileText = wx.StaticText(parent=self, label="Load from file")
            self.loadCalibrateFileNameText = wx.StaticText(parent=self, label="", size=(150, 25), pos=(150, 98),
                                                           style=wx.ST_ELLIPSIZE_START)
            self.loadCalibrateFileButton = wx.Button(parent=self, label="Load", size=(50, 26))
            self.staticLine = wx.StaticLine(parent=self, size=(370, 2), pos=(0, 130))
            self.OKButton = wx.Button(parent=self, label="OK", pos=(160, 140))
            self.cancelButton = wx.Button(parent=self, label="Cancel", pos=(250, 140))
            # add sizer
            self.gridSizer = wx.FlexGridSizer(cols=6, vgap=10, hgap=1)
            self.staticTextSizeFlag = wx.SizerFlags(1)
            self.staticTextSizeFlag.Border(wx.LEFT, 10).Align(wx.Bottom)
            self.textEntrySizerFlag = wx.SizerFlags(1)
            self.gridSizer.AddMany([(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (self.visualPlanText, self.staticTextSizeFlag),
                                    (self.visualPlanTextEntry, self.textEntrySizerFlag),
                                    (self.visualPlanUnit, self.staticTextSizeFlag),
                                    (self.visualPlanStepUpButton, 0, wx.ALIGN_LEFT, 0),
                                    (self.visualPlanStepDownButton, 0, wx.ALIGN_LEFT, 0),
                                    (self.visualPlanGoButton, 0, wx.ALIGN_LEFT, 0),

                                    (self.focusPlanText, self.staticTextSizeFlag),
                                    (self.focusPlanTextEntry, self.textEntrySizerFlag),
                                    (self.focusPlanUnit, self.staticTextSizeFlag),
                                    (self.focusPlanStepUpButton, 0, wx.ALIGN_LEFT, 0),
                                    (self.focusPlanStepDownButton, 0, wx.ALIGN_LEFT, 0),
                                    (self.focusPlanGoButton, 0, wx.ALIGN_LEFT, 0),

                                    (self.loadCalibrateFileText, self.staticTextSizeFlag),
                                    (self.loadCalibrateFileButton, 0, wx.ALIGN_LEFT, 0),
                                    ])
            self.SetSizer(self.gridSizer)
            # Bind Event
            self.Bind(wx.EVT_BUTTON, self.LoadFile, self.loadCalibrateFileButton)
            self.Bind(wx.EVT_BUTTON, self.SetFocusPlan, self.OKButton)
            self.Bind(wx.EVT_BUTTON, self.UpDownPlan, self.visualPlanStepUpButton)
            self.Bind(wx.EVT_BUTTON, self.UpDownPlan, self.visualPlanStepDownButton)
            self.Bind(wx.EVT_BUTTON, self.UpDownPlan, self.focusPlanStepUpButton)
            self.Bind(wx.EVT_BUTTON, self.UpDownPlan, self.focusPlanStepDownButton)
            self.Bind(wx.EVT_BUTTON, self.GoToPlan, self.visualPlanGoButton)
            self.Bind(wx.EVT_BUTTON, self.GoToPlan, self.focusPlanGoButton)
            self.Bind(wx.EVT_BUTTON, self.OnClose, self.cancelButton)
            self.Bind(wx.EVT_TEXT_ENTER, self.SetFocusPlan)

        def LoadFile(self, event):
            self.fileName = wx.FileSelector(message="Load File", default_path=".\\data\\",
                                            wildcard="PKL files (*.pkl)|*.pkl",
                                            flags=wx.FD_OPEN)
            if self.fileName.strip():
                self.loadCalibrateFileNameText.SetLabel("{}".format(self.fileName))
                logger.info("load {}".format(self.fileName))
                if "focusPlan.pkl" in self.fileName:
                    with open(self.fileName, "rb") as file:
                        try:
                            self.parent.focusPlan = pickle.load(file)
                            self.parent.visualPlan = pickle.load(file)
                            logger.info("successfully load focus plan file:{}".format(self.fileName))
                        except Exception as ex:
                            logger.error("failed load focus plan file because:{}".format(ex))
                            wx.MessageDialog.ShowModal(
                                wx.MessageDialog(parent=None,
                                                 message="exception accured in reading :"
                                                         "\n{}".format(self.fileName),
                                                 style=wx.OK))
                else:
                    wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None,
                                         message="Need load a focusPlan.pkl file.",
                                         style=wx.OK))

        def SetFocusPlan(self, event):
            self.parent.focusPlan["Z"] = round(float(self.focusPlanTextEntry.GetValue()), 3)
            self.parent.visualPlan["Z"] = round(float(self.visualPlanTextEntry.GetValue()), 3)
            if wx.MessageDialog.ShowModal(
                    wx.MessageDialog(parent=None,
                                     message="Want to Save to:"
                                             "\n{}".format(self.fileName),
                                     style=wx.YES_NO)) == wx.ID_YES:
                try:
                    with open(self.fileName, "wb+") as file:
                        pickle.dump(self.parent.focusPlan, file, 4)
                        pickle.dump(self.parent.visualPlan, file, 4)
                        logger.info("sucessfully save focus plan file:{}\n"
                                    "focus plan:{}, visual plan:{}".format(self.fileName, self.parent.focusPlan["Z"],
                                                                           self.parent.visualPlan["Z"]))
                        self.OnClose(event=None)
                except Exception as ex:
                    logger.error("failed save focus plan file because:{}".format(ex))
                    wx.MessageDialog.ShowModal(
                        wx.MessageDialog(parent=None,
                                         message="Failed to save:"
                                                 "\n{}".format(self.fileName),
                                         style=wx.OK))

        def UpDownPlan(self, event):
            buttonObj = event.GetButtonObj()
            try:
                if buttonObj == self.visualPlanStepUpButton:
                    self.parent.visualPlan["Z"] = round(float(self.visualPlanTextEntry.GetValue()), 3) + 0.01
                    self.parent.gcs.MOV(self.parent.visualPlan)
                elif buttonObj == self.visualPlanStepDownButton:
                    self.parent.visualPlan["Z"] = round(float(self.visualPlanTextEntry.GetValue()), 3) - 0.01
                    self.parent.gcs.MOV(self.parent.visualPlan)
                elif buttonObj == self.focusPlanStepUpButton:
                    self.parent.focusPlan["Z"] = round(float(self.focusPlanTextEntry.GetValue()), 3) + 0.01
                    self.parent.gcs.MOV(self.parent.focusPlan)
                elif buttonObj == self.focusPlanStepDownButton:
                    self.parent.focusPlan["Z"] = round(float(self.focusPlanTextEntry.GetValue()), 3) - 0.01
                    self.parent.gcs.MOV(self.parent.focusPlan)
                self.visualPlanTextEntry.SetValue("{}".format(self.parent.visualPlan["Z"]))
                self.focusPlanTextEntry.SetValue("{}".format(self.parent.focusPlan["Z"]))
            except Exception as ex:
                ShowErrorMessage(ex)

        def GoToPlan(self, event):
            buttonObj = event.GetButtonObj()
            try:
                if buttonObj == self.focusPlanGoButton:
                    self.parent.focusPlan["Z"] = round(float(self.focusPlanTextEntry.GetValue()), 3)
                    self.parent.gcs.MOV(self.parent.focusPlan)
                elif buttonObj == self.visualPlanGoButton:
                    self.parent.visualPlan["Z"] = round(float(self.visualPlanTextEntry.GetValue()), 3)
                    self.parent.gcs.MOV(self.parent.visualPlan)
            except Exception as ex:
                ShowErrorMessage(ex)

        def OnClose(self, event):
            self.Hide()
            self.parent.setFocusPlaneButton.SetToggle(False)

    class AutoFindFocuseDialog(InputDialog):

        def __init__(self, parent):
            self.parent = parent
            super(MainCameraPanel.AutoFindFocuseDialog, self).__init__(parent=self.parent, size=(320, 330),
                                                                       title="Auto find focuse plane")
            # add items
            self.lineLengthText = wx.StaticText(parent=self, label="Sample line length: ")
            self.lineLengthTextEntry = wx.TextCtrl(parent=self, value="0.5", style=wx.TE_PROCESS_ENTER)
            self.lineLengthUnit = wx.StaticText(parent=self, label="mm")
            self.lineSpaceText = wx.StaticText(parent=self, label="Space between two line: ")
            self.lineSpaceTextEntry = wx.TextCtrl(parent=self, value="0.1", style=wx.TE_PROCESS_ENTER)
            self.lineSpaceUnit = wx.StaticText(parent=self, label="mm")
            self.styleText = wx.StaticText(parent=self, label="Sample style: ")
            self.styleChoice = wx.Choice(parent=self, choices=["Line", "Spot"], size=(111, 25),
                                         style=wx.TAB_TRAVERSAL | wx.TE_PROCESS_ENTER)
            self.styleChoice.SetSelection(0)
            self.scanDirectionText = wx.StaticText(parent=self, label="Scan Direction: ")
            self.scanDirectionChoice = wx.Choice(parent=self, choices=["Horizontal", "Vertical"],size=(111, 25),
                                         style=wx.TAB_TRAVERSAL | wx.TE_PROCESS_ENTER)
            self.scanDirectionChoice.SetSelection(0)
            self.startPosText = wx.StaticText(parent=self, label="Start Z position: ")
            self.startPosTextEntry = wx.TextCtrl(parent=self, value="{}".format(self.parent.visualPlan["Z"]),
                                                 style=wx.TE_PROCESS_ENTER)
            self.startPosUnit = wx.StaticText(parent=self, label="mm")
            self.scanStepNumberText = wx.StaticText(parent=self, label="Scan step number: ")
            self.scanStepNumberTextEntry = wx.TextCtrl(parent=self, value="1", style=wx.TE_PROCESS_ENTER)
            self.stepSpaceText = wx.StaticText(parent=self, label="Step space: ")
            self.stepSpaceTextEntry = wx.TextCtrl(parent=self, value="0.05", style=wx.TE_PROCESS_ENTER)
            self.stepSpaceUnit = wx.StaticText(parent=self, label="mm")
            self.staticLine = wx.StaticLine(parent=self, pos=(0, 255), size=(320, 2))
            self.startButton = wx.Button(parent=self, label="Start", size=(111, 25))
            # add sizer
            self.gridSizer = wx.FlexGridSizer(cols=3, vgap=10, hgap=1)
            self.staticTextSizeFlag = wx.SizerFlags(0)
            self.staticTextSizeFlag.Border(wx.LEFT, 5).Align(wx.Bottom)
            self.sizerFlag = wx.SizerFlags(0)
            self.gridSizer.AddMany([(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (self.lineLengthText, self.staticTextSizeFlag),
                                    (self.lineLengthTextEntry, self.sizerFlag),
                                    (self.lineLengthUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.lineSpaceText, self.staticTextSizeFlag),
                                    (self.lineSpaceTextEntry, self.sizerFlag),
                                    (self.lineSpaceUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.styleText, self.staticTextSizeFlag),
                                    (self.styleChoice, self.sizerFlag),
                                    (0, 0, 0, 0),
                                    (self.scanDirectionText, self.staticTextSizeFlag),
                                    (self.scanDirectionChoice, self.sizerFlag),
                                    (0, 0, 0, 0),
                                    (self.startPosText, self.staticTextSizeFlag),
                                    (self.startPosTextEntry, self.sizerFlag),
                                    (self.startPosUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.scanStepNumberText, self.staticTextSizeFlag),
                                    (self.scanStepNumberTextEntry, self.sizerFlag),
                                    (0, 0, 0, 0),
                                    (self.stepSpaceText, self.staticTextSizeFlag),
                                    (self.stepSpaceTextEntry, self.sizerFlag),
                                    (self.stepSpaceUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (0, 0, 0, 0),
                                    (self.startButton, self.sizerFlag),
                                    ])
            self.SetSizer(self.gridSizer)
            # Bind Event
            self.Bind(wx.EVT_BUTTON, self.StarThread, self.startButton)

        def StarThread(self, event):
            startThread = threading.Thread(target=self.FindFocusePlan, daemon=True)
            startThread.start()

        def FindFocusePlan(self):
            try:
                self.parent.laserSpotTriggerButton.Disable()
                self.startButton.Disable()
                self.parent.circleDialog.runButton.Disable()
                lineLength = round(float(self.lineLengthTextEntry.GetValue()), 3)
                lineSpace = round(float(self.lineSpaceTextEntry.GetValue()), 3)
                style = self.styleChoice.GetSelection()
                scanDirection = self.scanDirectionChoice.GetSelection()
                scanStepNumber = int(self.scanStepNumberTextEntry.GetValue())
                stepSpace = round(float(self.stepSpaceTextEntry.GetValue()), 3)
                logger.info("start find focus plan, parameter:\n"
                            "linlen:{}, linSpa:{}, style:{}, scanStepNum:{}, stepSpace:{}"
                            .format(lineLength, lineSpace, style, scanStepNumber, stepSpace))
                pos = self.parent.gcs.qPOS(["X", "Y"])
                pos.setdefault("Z", self.parent.visualPlan["Z"])
                # go to the start z position
                self.parent.gcs.MOV({"Z": round(float(self.startPosTextEntry.GetValue()),3)})
                pitools.waitontarget(self.parent.gcs)
                # if set laser dialog haven't show, show it
                if not self.parent.setLaserButton.GetToggle():
                    self.parent.setLaserButton.SetToggle(True)
                    self.parent.setLaserDialog.Show()
                # check if laser is power on, if not power it on
                if self.parent.setLaserDialog.GetPowerState() != "PowerOn":
                    self.parent.setLaserDialog.PowerOn()
                self.parent.setLaserDialog.SetLaserParameter()
                if scanDirection == 0:
                    # if scan direction is horicental...
                    for i in range(scanStepNumber):
                        if style == 0:
                            # laser darw line
                            self.parent.setLaserDialog.ContinueRun()
                            self.parent.gcs.MVR({"X": lineLength})
                            pitools.waitontarget(self.parent.gcs)
                            self.parent.setLaserDialog.Pause()
                        else:
                            # set burst mode to trigger, if it is not
                            if self.parent.setLaserDialog.GetModeContinueOrTrigger() != "Trigger":
                                self.parent.setLaserDialog.SetModeTrigger()
                            self.parent.setLaserDialog.LaserRun()
                            for j in range(10):
                                # trigger laser
                                self.parent.setLaserDialog.SetModeTrigger()
                                # wait trigger start
                                time.sleep(0.2)
                                # wait trigger finish
                                while self.parent.setLaserDialog.GetBurstToGo() != "0.0":
                                    time.sleep(0.2)
                                self.parent.gcs.MVR({"X": lineLength / 10})
                                pitools.waitontarget(self.parent.gcs)
                        self.parent.gcs.MVR({"X": -lineLength, "Y": -lineSpace, "Z": stepSpace})
                        pitools.waitontarget(self.parent.gcs)
                else:
                    # if scan direction is vertical
                    for i in range(scanStepNumber):
                        if style == 0:
                            # laser darw line
                            self.parent.setLaserDialog.ContinueRun()
                            self.parent.gcs.MVR({"Y": -lineLength})
                            pitools.waitontarget(self.parent.gcs)
                            self.parent.setLaserDialog.Pause()
                        else:
                            # set burst mode to trigger, if it is not
                            if self.parent.setLaserDialog.GetModeContinueOrTrigger() != "Trigger":
                                self.parent.setLaserDialog.SetModeTrigger()
                            self.parent.setLaserDialog.LaserRun()
                            for j in range(10):
                                # trigger laser
                                self.parent.setLaserDialog.SetModeTrigger()
                                # wait trigger start
                                time.sleep(0.2)
                                # wait trigger finish
                                while self.parent.setLaserDialog.GetBurstToGo() != "0.0":
                                    time.sleep(0.2)
                                self.parent.gcs.MVR({"Y": -lineLength / 10})
                                pitools.waitontarget(self.parent.gcs)
                        self.parent.gcs.MVR({"X": lineSpace, "Y": lineLength, "Z": stepSpace})
                        pitools.waitontarget(self.parent.gcs)
                logger.info("Successfully finish auto find focuse plan")
            except Exception as ex:
                self.parent.setLaserDialog.PowerOff()
                logger.error("failed do auto find focus plan because:{}".format(ex))
                ShowErrorMessage("failed do auto find focus plan because:{}".format(ex))
            finally:
                self.parent.laserSpotTriggerButton.Enable()
                self.startButton.Enable()
                self.parent.circleDialog.runButton.Enable()
                self.parent.gcs.MOV(pos)
                pitools.waitontarget(self.parent.gcs)

        def OnClose(self, event):
            self.Hide()
            self.parent.findFocusPlaneButton.SetToggle(False)

    class ZigZagDialog(InputDialog):

        def __init__(self, parent):
            self.parent = parent
            super(MainCameraPanel.ZigZagDialog, self).__init__(parent=self.parent, size=(300, 270),
                                                               title="Zig zag process")
            # add items
            self.lineLengthText = wx.StaticText(parent=self, label="Sample line length: ")
            self.lineLengthTextEntry = wx.TextCtrl(parent=self, value="0.5", style=wx.TE_PROCESS_ENTER)
            self.lineLengthUnit = wx.StaticText(parent=self, label="mm")
            self.lineSpaceText = wx.StaticText(parent=self, label="Space between\ntwo line: ")
            self.lineSpaceTextEntry = wx.TextCtrl(parent=self, value="0.1", style=wx.TE_PROCESS_ENTER)
            self.lineSpaceUnit = wx.StaticText(parent=self, label="mm")

            self.lineNumberText = wx.StaticText(parent=self, label="Number of lines: ")
            self.lineNumberTextEntry = wx.TextCtrl(parent=self, value="2", style=wx.TE_PROCESS_ENTER)
            self.scanDirectionText = wx.StaticText(parent=self, label="Scan Direction: ")
            self.scanDirectionChoice = wx.Choice(parent=self, choices=["Horizontal", "Vertical"], size=(111, 25),
                                                 style=wx.TAB_TRAVERSAL | wx.TE_PROCESS_ENTER)
            self.scanDirectionChoice.SetSelection(0)
            self.speedText = wx.StaticText(parent=self, label="speed: ")
            self.speedTextEntry = wx.TextCtrl(parent=self, value="10", style=wx.TE_PROCESS_ENTER)
            self.speedUnit = wx.StaticText(parent=self, label="mm/s")
            self.staticLine = wx.StaticLine(parent=self, pos=(0, 195), size=(300, 2))
            self.startButton = wx.Button(parent=self, label="Start", size=(111, 25))
            # add sizer
            self.gridSizer = wx.FlexGridSizer(cols=3, vgap=10, hgap=1)
            self.staticTextSizeFlag = wx.SizerFlags(0)
            self.staticTextSizeFlag.Border(wx.LEFT, 5).Align(wx.Bottom)
            self.sizerFlag = wx.SizerFlags(0)
            self.gridSizer.AddMany([(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (self.lineLengthText, self.staticTextSizeFlag),
                                    (self.lineLengthTextEntry, self.sizerFlag),
                                    (self.lineLengthUnit, 0, wx.ALIGN_LEFT | wx.LEFT, 10),
                                    (self.lineSpaceText, self.staticTextSizeFlag),
                                    (self.lineSpaceTextEntry, self.sizerFlag),
                                    (self.lineSpaceUnit, 0, wx.ALIGN_LEFT | wx.LEFT, 10),
                                    (self.lineNumberText, self.staticTextSizeFlag),
                                    (self.lineNumberTextEntry, self.sizerFlag),
                                    (0, 0, 0, 0),
                                    (self.scanDirectionText, self.staticTextSizeFlag),
                                    (self.scanDirectionChoice, self.sizerFlag),
                                    (0, 0, 0, 0),
                                    (self.speedText, self.staticTextSizeFlag),
                                    (self.speedTextEntry, self.sizerFlag),
                                    (self.speedUnit, 0, wx.ALIGN_LEFT | wx.LEFT, 10),
                                    (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (0, 0, 0, 0),
                                    (self.startButton, self.sizerFlag),
                                    ])
            self.SetSizer(self.gridSizer)
            # Bind Event
            self.Bind(wx.EVT_BUTTON, self.StarThread, self.startButton)

        def StarThread(self, event):
            startThread = threading.Thread(target=self.ZigZag, daemon=True)
            startThread.start()

        def ZigZag(self):
            try:
                self.parent.laserSpotTriggerButton.Disable()
                self.startButton.Disable()
                self.parent.circleDialog.runButton.Disable()
                lineLength = round(float(self.lineLengthTextEntry.GetValue()), 3)
                lineSpace = round(float(self.lineSpaceTextEntry.GetValue()), 3)
                lineNumber = int(self.lineNumberTextEntry.GetValue())
                scanDirection = self.scanDirectionChoice.GetSelection()
                speed = round(float(self.speedTextEntry.GetValue()), 3)
                pos = self.parent.gcs.qPOS(["X", "Y"])
                pos.setdefault("Z", self.parent.visualPlan["Z"])
                if not (0 < speed <= 10):
                    raise Exception("speed out of limit, range (0, 10]")
                logger.info("start zig zag process, parameter:\n"
                            "linlen:{}, linSpa:{}, linNum:{}, speed:{}"
                            .format(lineLength, lineSpace, lineNumber, speed))
                # if set laser dialog haven't show, show it
                if not self.parent.setLaserButton.GetToggle():
                    self.parent.setLaserButton.SetToggle(True)
                    self.parent.setLaserDialog.Show()
                # check if laser is power on, if not power it on
                if self.parent.setLaserDialog.GetPowerState() != "PowerOn":
                    self.parent.setLaserDialog.PowerOn()
                self.parent.gcs.MOV(self.parent.focusPlan)
                pitools.waitontarget(self.parent.gcs)
                self.parent.gcs.VLS(speed)
                self.parent.setLaserDialog.ContinueRun()
                if scanDirection == 0:
                    for i in range(lineNumber):
                        # laser darw line
                        self.parent.gcs.MVR({"X": ((-1) ** i * lineLength)})
                        pitools.waitontarget(self.parent.gcs)
                        self.parent.gcs.MVR({"Y": -lineSpace})
                        pitools.waitontarget(self.parent.gcs)
                else:
                    for i in range(1, lineNumber+1):
                        # laser darw line
                        self.parent.gcs.MVR({"Y": ((-1) ** i * lineLength)})
                        pitools.waitontarget(self.parent.gcs)
                        self.parent.gcs.MVR({"X": lineSpace})
                        pitools.waitontarget(self.parent.gcs)
                self.parent.setLaserDialog.Pause()
                logger.info("Successfully finish auto find focuse plan")
            except Exception as ex:
                if ex.args != "speed out of limit, range (0, 10]":
                    pass
                    # self.parent.setLaserDialog.PowerOff()
                logger.error("failed do zig zag process because:{}".format(ex))
                ShowErrorMessage("failed do zig zag process because:{}".format(ex))
            finally:
                self.parent.laserSpotTriggerButton.Enable()
                self.startButton.Enable()
                self.parent.circleDialog.runButton.Enable()
                self.parent.gcs.VLS(10)
                self.parent.gcs.MOV(pos)
                pitools.waitontarget(self.parent.gcs)

        def OnClose(self, event):
            self.Hide()
            self.parent.zigZagButton.SetToggle(False)

    class SetLaserDialog(InputDialog):

        class TextCtrl(wx.TextCtrl):
            def __init__(self, uplimit=100, downlimit=0, diff=0.1, *args, **kwargs):
                super(wx.TextCtrl, self).__init__(*args, **kwargs)
                self.uplimit = uplimit
                self.downlimit = downlimit
                self.diff = diff
                if self.diff.__class__ is int:
                    self.integer = True
                else:
                    self.integer = False
                self.Bind(wx.EVT_KEY_DOWN, self.AddNumber)

            def AddNumber(self, event):
                try:
                    event.keyCode = event.GetKeyCode()
                    if event.keyCode == 315 or event.keyCode == 317:
                        if self.integer:
                            currentValue = int(self.GetValue())
                        else:
                            currentValue = float(self.GetValue())
                        if event.keyCode == 315:
                            currentValue = currentValue + self.diff
                        elif event.keyCode == 317:
                            currentValue = currentValue - self.diff
                        if self.downlimit <= currentValue <= self.uplimit:
                            self.SetValue(value="{}".format(round(currentValue, 1)))
                            self.Parent.SetLaserParameter()
                    else:
                        pass
                except Exception as ex:
                    ShowErrorMessage(ex)
                finally:
                    event.Skip()

        def __init__(self, parent):
            self.parent = parent
            super(MainCameraPanel.SetLaserDialog, self).__init__(parent=self.parent, title="Set laser parameter",
                                                                 size=(288, 262))
            # add item
            self.attenuatorText = wx.StaticText(parent=self, label="Attenuator:")
            self.attenuatorTextEntry = self.TextCtrl(uplimit=100, downlimit=0, diff=0.1,
                                                     parent=self, value="0.0", style=wx.TE_PROCESS_ENTER)
            self.attenuatorUnity = wx.StaticText(parent=self, label="%")
            self.repetitionRateText = wx.StaticText(parent=self, label="Repetition rate:")
            self.repetitionRateTextEntry = self.TextCtrl(uplimit=1000, downlimit=200, diff=1,
                                                         parent=self, value="200", style=wx.TE_PROCESS_ENTER)
            self.repetitionRateUnitText = wx.StaticText(parent=self, label="kHz")
            self.frequencyDividerText = wx.StaticText(parent=self, label="Frequency divider:")
            self.frequencyDividerTextEntry = self.TextCtrl(uplimit=1025, downlimit=1, diff=1,
                                                           parent=self, value="1", style=wx.TE_PROCESS_ENTER)
            self.harmonicsText = wx.StaticText(parent=self, label="Hamrmonics:")
            self.harmonicsChoice = wx.Choice(parent=self, choices=["IH", "IIH", "IIIH"], size=(111, 25),
                                             style=wx.TAB_TRAVERSAL | wx.TE_PROCESS_ENTER)
            self.harmonicsChoice.SetSelection(0)
            self.burstLengthText = wx.StaticText(parent=self, label="Burst length:")
            self.burstLengthTextEntry = self.TextCtrl(uplimit=16777216, downlimit=1, diff=1,
                                                      parent=self, value="1", style=wx.TE_PROCESS_ENTER)
            self.burstLengthUnit = wx.StaticText(parent=self, label="pulse")
            self.emitteLaserButton = FunctionToggleButtons(parent=self, name=".\\icon\\emit_laser.bmp", pos=(5, 182))
            self.emitteLaserButton.SetBitmapSelected(name=".\\icon\\emit_laserON.bmp")
            self.runButton = FunctionButtons(parent=self, name=".\\icon\\runlaser.bmp", pos=(90, 182))
            self.pauseButton = FunctionButtons(parent=self, name=".\\icon\\pauselaser.bmp", pos=(130, 182))
            self.setButton = FunctionButtons(parent=self, name=".\\icon\\set.bmp", pos=(170, 182))
            self.laserWarningPanel = wx.Panel(parent=self, size=(60, 40), pos=(210, 182))
            self.laserWarningPanel.DC = wx.ClientDC(self.laserWarningPanel)
            self.laserWarningPanel.bmpW = wx.Bitmap()
            self.laserWarningPanel.bmpW.LoadFile(".\\icon\\laserwarningW.bmp")
            self.laserWarningPanel.bmpY = wx.Bitmap()
            self.laserWarningPanel.bmpY.LoadFile(".\\icon\\laserwarningY.bmp")
            self.laserWarningPanel.bmpG = wx.Bitmap()
            self.laserWarningPanel.bmpG.LoadFile(".\\icon\\laserwarningG.bmp")
            self.laserWarningPanel.bmpR = wx.Bitmap()
            self.laserWarningPanel.bmpR.LoadFile(".\\icon\\laserwarningR.bmp")
            # add sizer
            self.gridSizer = wx.FlexGridSizer(cols=3, vgap=10, hgap=1)
            self.staticTextSizeFlag = wx.SizerFlags(0)
            self.staticTextSizeFlag.Border(wx.LEFT, 5).Align(wx.Bottom)
            self.sizerFlag = wx.SizerFlags(0)
            self.gridSizer.AddMany([(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                                    (self.attenuatorText, self.staticTextSizeFlag),
                                    (self.attenuatorTextEntry, self.sizerFlag),
                                    (self.attenuatorUnity, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.repetitionRateText, self.staticTextSizeFlag),
                                    (self.repetitionRateTextEntry, self.sizerFlag),
                                    (self.repetitionRateUnitText, 0, wx.ALIGN_CENTER | wx.RIGHT, 10),
                                    (self.frequencyDividerText, self.staticTextSizeFlag),
                                    (self.frequencyDividerTextEntry, self.sizerFlag),
                                    (0, 0, 0, 0),
                                    (self.harmonicsText, self.staticTextSizeFlag),
                                    (self.harmonicsChoice, self.sizerFlag),
                                    (0, 0, 0, 0),
                                    (self.burstLengthText, self.staticTextSizeFlag),
                                    (self.burstLengthTextEntry, self.sizerFlag),
                                    (self.burstLengthUnit, 0, wx.ALIGN_CENTER | wx.RIGHT, 10)
                                    ])
            self.SetSizer(self.gridSizer)
            self.staticLine = wx.StaticLine(parent=self, pos=(5, 180), size=(281, 2))
            # bind function
            # initial properties
            self.attenuator = 0.0
            self.repetitionRate = 200
            self.frequencyDivider = 1
            self.harmonics = 0
            self.burstLength = 1
            self.powerStateDictionary = {"2.0": "PowerOff", "9.0": "PowerOn", "11.0": "Run", "12.0": "Fault"}
            # bind event
            self.Bind(wx.EVT_BUTTON, self.ButtonThread, self.emitteLaserButton)
            self.Bind(wx.EVT_BUTTON, self.ButtonThread, self.runButton)
            self.Bind(wx.EVT_BUTTON, self.ButtonThread, self.pauseButton)
            self.Bind(wx.EVT_BUTTON, self.SetLaserParameterEventHandler, self.setButton)
            self.Bind(wx.EVT_TEXT_ENTER, self.SetLaserParameterEventHandler)
            # # initial laser parameter setting
            # self.SetLaserParameter()

        def SetLaserParameterEventHandler(self, event):
            try:
                self.SetLaserParameter()
            except Exception as ex:
                logger.error("failed set laser parameter because:{}".format(ex))
                ShowErrorMessage("failed set laser parameter because:\n{}".format(ex))

        def ButtonThread(self, event):
            obj = event.GetButtonObj()
            threadList = threading.enumerate()
            nameList = []
            for i in range(len(threadList)):
                nameList.append(threadList[i].name)
            if "PowerOnOff" not in nameList and "Run" not in nameList and "Pause" not in nameList:
                if obj is self.emitteLaserButton:
                    thread = threading.Thread(target=self.PowerOnOffLaser, name="PowerOnOff")
                elif obj is self.runButton:
                    thread = threading.Thread(target=self.ContinueRun, name="Run")
                elif obj is self.pauseButton:
                    thread = threading.Thread(target=self.Pause, name="Pause")
                thread.start()

        def ContinueRun(self):
            try:
                # set laser parameter
                self.SetLaserParameter()
                # set mode continue
                self.SetModeContinue()
                # start running laser
                self.LaserRun()
                logger.info("successfully running laser continue")
            except Exception as ex:
                self.FatalErrorProcess(ex)

        def Pause(self):
            # only pause when laserRunning
            try:
                if self.GetPowerState() is "Run":
                    # command 3 and state 9 indicate pause
                    self.parent.laser.SendCommand("rcSetRegNVFromDouble SY3PILA:32 Command 3")
                    self.WaitForLaser(State="9.0")
                    self.laserWarningPanel.DC.DrawBitmap(self.laserWarningPanel.bmpY, x=-1, y=-1)
                    logger.info("successfully pause laser")
            except Exception as ex:
                self.FatalErrorProcess(ex)

        def PowerOnOffLaser(self):
            try:
                if not self.emitteLaserButton.GetToggle():
                    self.PowerOff()
                else:
                    self.PowerOn()
            except Exception as ex:
                self.FatalErrorProcess(ex)

        def LaserRun(self):
            try:
                # check laser power on, if not power on
                if self.GetPowerState() is not "PowerOn":
                    self.PowerOn()
                self.parent.laser.SendCommand("rcSetRegNVFromDouble SY3PILA:32 Command 4")
                self.WaitForLaser(State="11.0")
                self.laserWarningPanel.DC.DrawBitmap(self.laserWarningPanel.bmpG, x=-1, y=-1)
                logger.info("successfully run laser")
            except Exception as ex:
                raise ex

        def PowerOn(self):
            try:
                self.emitteLaserButton.SetToggle(True)
                # command 3 and state 9 indicate pause
                self.parent.laser.SendCommand("rcSetRegNVFromDouble SY3PILA:32 Command 3")
                self.WaitForLaser(State="9.0")
                self.laserWarningPanel.DC.DrawBitmap(self.laserWarningPanel.bmpY, x=-1, y=-1)
                logger.info("sucessfully power on laser")
            except Exception as ex:
                raise ex

        def PowerOff(self):
            try:
                self.emitteLaserButton.SetToggle(False)
                # command 1 and state 2 indicate sleep
                logger.info("Power off laser")
                self.parent.laser.SendCommand("rcSetRegNVFromDouble SY3PILA:32 Command 1")
                self.WaitForLaser(State="2.0")
                self.laserWarningPanel.DC.DrawBitmap(self.laserWarningPanel.bmpW, x=-1, y=-1)
                logger.info("successfully power off laser")
            except Exception as ex:
                logger.error(ex)

        def WaitForLaser(self, State="2"):
            i = 0
            currentState = self.parent.laser.SendCommand("rcGetRegAsDouble SY3PILA:32 Current__State")
            while currentState != State:
                # state 12 indicate fault
                if currentState == "12.0":
                    self.CatchLaserFalut()
                else:
                    if i % 2:
                        self.laserWarningPanel.DC.DrawBitmap(self.laserWarningPanel.bmpW, x=-1, y=-1)
                    else:
                        self.laserWarningPanel.DC.DrawBitmap(self.laserWarningPanel.bmpY, x=-1, y=-1)
                    i = i + 1
                    time.sleep(0.5)
                    currentState = self.parent.laser.SendCommand("rcGetRegAsDouble SY3PILA:32 Current__State")

        def CatchLaserFalut(self):
            # collect Error Code from laser
            ErrorReg = ["SY3PILA:32", "PS20100:16", "PS20100:17", "LDD1A:18", "LDCO48BP:24", "LDCO48BP:25",
                        "LDCO48BP:26", "LDCO48BP:27", "HV40W:40"]
            ErrCode = ""
            for i in range(len(ErrorReg)):
                try:
                    ErrCode = "{} ERROR:".format(ErrorReg[i]) + \
                              self.parent.laser.SendCommand("rcGetRegAsString {} Error__Code".format(ErrorReg[i])) \
                              + "\n"
                except:
                    pass
            raise Exception(ErrCode)

        def FatalErrorProcess(self, ex):
            self.PowerOff()
            try:
                self.CatchLaserFalut()
            except Exception as laserEx:
                ex.args = (ex.__str__() + laserEx.__str__(),)
            self.laserWarningPanel.DC.DrawBitmap(self.laserWarningPanel.bmpR, x=-1, y=-1)
            logger.error("Faild running laser,error code:{}".format(ex))
            ShowErrorMessage("failed running laser because:\n{}\n, laser is now power off".format(ex))

        def GetModeContinueOrTrigger(self):
            try:
                return self.parent.laser.SendCommand("rcGetRegAsString SY3PILA:32 "
                                                     "Continuous__/__Burst__mode__/__Trigger__burst")
            except Exception as ex:
                raise ex

        def SetModeContinue(self):
            try:
                self.parent.laser.SendCommand(
                    "rcSetRegFromString SY3PILA:32 Continuous__/__Burst__mode__/__Trigger__burst"
                    " Continuous")
                logger.info("successfully set laser continue")
            except Exception as ex:
                raise ex

        def SetModeTrigger(self):
            try:
                self.parent.laser.SendCommand(
                    "rcSetRegFromString SY3PILA:32 Continuous__/__Burst__mode__/__Trigger__burst"
                    " Trigger")
                logger.info("successfully set laser trigger")
            except Exception as ex:
                raise ex

        def GetPowerState(self):
            try:
                currentState = self.parent.laser.SendCommand("rcGetRegAsDouble SY3PILA:32 Current__State")
                return self.powerStateDictionary[currentState]
            except Exception as ex:
                raise ex

        def GetBurstToGo(self):
            try:
                return self.parent.laser.SendCommand("rcGetRegAsDouble SY3PILA:32 Burst__pulses__to__go")
            except Exception as ex:
                raise ex

        def SetLaserParameter(self):
            self.attenuator = round(float(self.attenuatorTextEntry.GetValue()), 1)
            self.repetitionRate = int(self.repetitionRateTextEntry.GetValue())
            self.frequencyDivider = int(self.frequencyDividerTextEntry.GetValue())
            self.harmonics = int(self.harmonicsChoice.GetSelection())
            self.burstLength = int(self.burstLengthTextEntry.GetValue())
            checkFlage = True
            if not (0 <= self.attenuator <= 100):
                ShowErrorMessage("ParameterError:Attenuator out of limit. range(0,100)")
                checkFlage = False
            if not (200 <= self.repetitionRate <= 1000):
                ShowErrorMessage("ParameterError:Repetition rate out of limit. range(200,1000)")
                checkFlage = False
            if not (1 <= self.frequencyDivider <= 1025):
                ShowErrorMessage("ParameterError:Frequency divider out of limit. range(1,1025)")
                checkFlage = False
            if not (1 <= self.burstLength <= 16777216):
                ShowErrorMessage("ParameterError:Burst length out of limit. range(1,16777216)")
                checkFlage = False
            if not checkFlage:
                return
            else:
                try:
                    self.parent.laser.SendCommand("rcSetRegNVFromDouble SY3PILA:32 Attenuator {}".
                                                  format(self.attenuator))
                    self.parent.laser.SendCommand("rcSetRegNVFromDouble SY3PILA:32 Repetition__rate {}".
                                                  format(self.repetitionRate))
                    self.parent.laser.SendCommand("rcSetRegNVFromDouble SY3PILA:32 Frequency__divider {}".
                                                  format(self.frequencyDivider))
                    self.parent.laser.SendCommand("rcSetRegNVFromString SY3PILA:32 Harmonics__module__position {}".
                                                  format(["IH", "IIH", "IIIH"][self.harmonics]))
                    self.parent.laser.SendCommand("rcSetRegFromDouble SY3PILA:32 Burst__length,__pulses {}".
                                                  format(self.burstLength))
                    logger.info("succesfully set laser parameter:\n"
                                "AttNua:{}, RepRat:{}, FreDiv:{}, Har:{}, BurLen:{}".
                                format(self.attenuator, self.repetitionRate,
                                       self.frequencyDivider, self.harmonics, self.burstLength))
                except Exception as ex:
                    raise ex

        def OnClose(self, event):
            self.Hide()
            self.parent.setLaserButton.SetToggle(False)


def main():
    try:
        # start main app
        app = App()
        # App wait for event
        app.MainLoop()
    except Exception as exception:
        # when fatal error appeared, remained user to contact admin, and log bug
        errorapp = wx.App()
        wx.MessageDialog.ShowModal(
            wx.MessageDialog(parent=None, message="FATAL ERROR has appeared, Pleas call admin(Han Zhao)",
                             caption="Pleas report bug", style=wx.OK))
        logger.fatal(exception)
        sys.excepthook.handle(sys.exc_info())
    finally:
        logger.info("App closed")

# main entrance
if __name__ == '__main__':
    main()