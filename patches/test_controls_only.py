#!/usr/bin/env python3
"""Pinned-source regression guard; no daemon, Bluetooth or audio is started.

These are structural guards, not a Qt integration/hardware test. Exact allowed
bodies ensure all activation entry points are inert, including retries and
WirePlumber recovery, while retaining identity tracking for ear/CA handling.
"""
import pathlib
import re
import sys
import unittest

SOURCE = pathlib.Path(sys.argv.pop(1))
TEXT = (SOURCE / 'daemon/media/mediacontroller.cpp').read_text()


def body(name):
    match = re.search(r'(?:bool|void) MediaController::' + name + r'\([^)]*\)\s*\{', TEXT)
    assert match, name
    start = match.end()
    depth = 1
    end = start
    while depth:
        depth += (TEXT[end] == '{') - (TEXT[end] == '}')
        end += 1
    value = re.sub(r'//[^\n]*', '', TEXT[start:end-1])
    return ' '.join(value.split())


class ControlsOnly(unittest.TestCase):
    def test_profile_policy_is_external(self):
        expected = {
            'activateA2dpProfile': 'return false;',
            'activateA2dpProfileWithRetry': 'setConnectedDeviceMacAddress(macAddress);',
            'attemptA2dpActivation': '',
            'restartWirePlumber': 'return false;',
            'removeAudioOutputDevice': '',
        }
        for name, value in expected.items():
            with self.subTest(method=name):
                self.assertEqual(body(name), value)
        self.assertNotIn('m_pulseAudio->setCardProfile(', TEXT)
        self.assertNotIn('m_pulseAudio->enableVolumeSnap(', TEXT)

    def test_controls_and_ear_playback_remain(self):
        self.assertIn('pause();', body('handleEarDetection'))
        self.assertIn('play();', body('handleEarDetection'))
        main = (SOURCE / 'daemon/main.cpp').read_text()
        for verb in ('noise:anc', 'noise:transparency', 'noise:adaptive', 'ca:on', 'onebud:on', 'ear:off'):
            self.assertIn('"' + verb + '"', main)
        enums = (SOURCE / 'daemon/enums.h').read_text()
        for model in ('A3055', 'A3056', 'A3057'):
            self.assertIn('{"' + model + '", AirPodsModel::AirPods4ANC}', enums)


if __name__ == '__main__':
    unittest.main()
