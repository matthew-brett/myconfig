##########################
Other notes for setting up
##########################

Activating the numeric keypad:

http://tipotheday.com/2008/04/30/slim-aluminum-apple-keyboard-with-ubuntu-hardy-heron/

Making Fn be down by default for Apple keyboard:

https://wiki.archlinux.org/index.php/Apple_Keyboard

Particularly::

    echo 2 > /sys/module/hid_apple/parameters/fnmode

into ``/etc/modprobe.d/hid_apple.conf``
