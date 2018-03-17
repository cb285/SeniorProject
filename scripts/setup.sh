#!/bin/bash

su

# gui
apt install python-pip python3-pip libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev pkg-config libgl1-mesa-dev libgles2-mesa-dev python-setuptools libgstreamer1.0-dev git-core gstreamer1.0-plugins-{bad,base,good,ugly} gstreamer1.0-{omx,alsa} python-dev xorg-dev
pip3 install cython
pip3 install git+https://github.com/kivy/kivy.git
pip3 install requests

# server
pip3 install XBee
pip3 install Flask
pip3 install Flask-BasicAuth
apt install openssl
pip3 install pyopenssl
pip3 install apscheduler
pip3 install SQLAlchemy
apt install python3-systemd

# localtunnel
#apt install npm
#npm install -g localtunnel
#cp ./scripts/localtunnel.service /etc/systemd/system/
#systemctrl daemon-reload
#systemctrl enable localtunnel.service
#systemctrl start localtunnel.service
#ln -s /usr/bin/nodejs /usr/bin/node


# enable touchscreen for kivy https://github.com/mrichardson23/rpi-kivy-screen
