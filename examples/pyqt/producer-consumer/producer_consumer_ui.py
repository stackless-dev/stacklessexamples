# -*- coding: utf-8 -*-

# Used by producer_consumer.py

# Form implementation generated from reading ui file 'prodcon_ui.ui'
#
# Created: Tue Aug 29 15:41:04 2006
#      by: PyQt4 UI code generator 4-snapshot-20060814
#
# WARNING! All changes made in this file will be lost!

import sys
from PyQt4 import QtCore, QtGui

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(QtCore.QSize(QtCore.QRect(0,0,392,351).size()).expandedTo(MainWindow.minimumSizeHint()))

        self.centralwidget = QtGui.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")

        self.cons = QtGui.QLineEdit(self.centralwidget)
        self.cons.setGeometry(QtCore.QRect(80,170,31,20))
        self.cons.setObjectName("cons")

        self.stop = QtGui.QPushButton(self.centralwidget)
        self.stop.setGeometry(QtCore.QRect(60,70,75,23))
        self.stop.setObjectName("stop")

        self.start = QtGui.QPushButton(self.centralwidget)
        self.start.setGeometry(QtCore.QRect(60,40,75,23))
        self.start.setObjectName("start")

        self.addprod = QtGui.QPushButton(self.centralwidget)
        self.addprod.setGeometry(QtCore.QRect(270,160,75,23))
        self.addprod.setObjectName("addprod")

        self.label = QtGui.QLabel(self.centralwidget)
        self.label.setGeometry(QtCore.QRect(20,150,48,14))
        self.label.setObjectName("label")

        self.prod = QtGui.QLineEdit(self.centralwidget)
        self.prod.setGeometry(QtCore.QRect(80,150,31,20))
        self.prod.setObjectName("prod")

        self.addcons = QtGui.QPushButton(self.centralwidget)
        self.addcons.setGeometry(QtCore.QRect(270,130,75,23))
        self.addcons.setObjectName("addcons")

        self.label_2 = QtGui.QLabel(self.centralwidget)
        self.label_2.setGeometry(QtCore.QRect(20,171,53,14))
        self.label_2.setObjectName("label_2")

        self.add = QtGui.QPushButton(self.centralwidget)
        self.add.setGeometry(QtCore.QRect(270,40,75,23))
        self.add.setObjectName("add")

        self.lcdNumber = QtGui.QLCDNumber(self.centralwidget)
        self.lcdNumber.setGeometry(QtCore.QRect(170,40,64,23))
        self.lcdNumber.setObjectName("lcdNumber")

        self.queue = QtGui.QProgressBar(self.centralwidget)
        self.queue.setGeometry(QtCore.QRect(190,80,22,211))
        self.queue.setMaximum(60)
        self.queue.setProperty("value",QtCore.QVariant(0))
        self.queue.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignTop)
        self.queue.setOrientation(QtCore.Qt.Vertical)
        self.queue.setInvertedAppearance(False)
        self.queue.setTextDirection(QtGui.QProgressBar.TopToBottom)
        self.queue.setObjectName("queue")
        MainWindow.setCentralWidget(self.centralwidget)

        self.menubar = QtGui.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0,0,392,21))
        self.menubar.setObjectName("menubar")
        MainWindow.setMenuBar(self.menubar)

        self.statusbar = QtGui.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)
        QtCore.QObject.connect(self.queue,QtCore.SIGNAL("valueChanged(int)"),self.lcdNumber.display)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QtGui.QApplication.translate("MainWindow", "MainWindow", None, QtGui.QApplication.UnicodeUTF8))
        self.stop.setText(QtGui.QApplication.translate("MainWindow", "Stop", None, QtGui.QApplication.UnicodeUTF8))
        self.start.setText(QtGui.QApplication.translate("MainWindow", "Start", None, QtGui.QApplication.UnicodeUTF8))
        self.addprod.setText(QtGui.QApplication.translate("MainWindow", "+ Prod", None, QtGui.QApplication.UnicodeUTF8))
        self.label.setText(QtGui.QApplication.translate("MainWindow", "Producers", None, QtGui.QApplication.UnicodeUTF8))
        self.addcons.setText(QtGui.QApplication.translate("MainWindow", "+ Cons", None, QtGui.QApplication.UnicodeUTF8))
        self.label_2.setText(QtGui.QApplication.translate("MainWindow", "Consumers", None, QtGui.QApplication.UnicodeUTF8))
        self.add.setText(QtGui.QApplication.translate("MainWindow", "+10", None, QtGui.QApplication.UnicodeUTF8))
