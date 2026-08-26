"""Bluetooth do robo: o celular fala com o Pi direto, sem ESP32 no meio."""

from roboteye.ble.mqtt import EntregaMqtt
from roboteye.ble.nus import NUS_RX, NUS_SERVICE, NUS_TX, PonteBLE, anunciar_pelo_kernel

__all__ = [
    "NUS_RX",
    "NUS_SERVICE",
    "NUS_TX",
    "EntregaMqtt",
    "PonteBLE",
    "anunciar_pelo_kernel",
]
