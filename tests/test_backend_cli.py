import contextlib, io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from companion import backend

class CLITest(unittest.TestCase):
    def test_status_cli_through_real_symlink_with_mocked_executables(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);bin_dir=p/"commands";bin_dir.mkdir()
            for name,output in [("pw-dump","[]"),("busctl",'{"data":[{}]}')]:
                f=bin_dir/name
                f.write_text("#!/usr/bin/python3\nprint("+repr(output)+")\n");f.chmod(0o700)
            link=p/"entry";link.symlink_to(Path(__file__).resolve().parents[1]/"bin/gnome-airpods-companion")
            result=subprocess.run(["/usr/bin/python3",str(link),"status"],env=dict(os.environ,PATH=str(bin_dir),XDG_STATE_HOME=str(p/"state")),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads(result.stdout)
            self.assertEqual(data["schema_version"],1)
            self.assertFalse(data["connected"])
            self.assertFalse((p/"state").exists())

    def test_cli_mode_persists_real_intent(self):
        from companion.cli import main
        with tempfile.TemporaryDirectory() as t:
            app=backend.Backend(Path(t),lambda args: "[]" if args[0]=="pw-dump" else json.dumps({"data":[{"/test":{"org.bluez.Device1":{"Name":{"data":"Test AirPods"},"Address":{"data":"00:11:22:33:44:55"},"Paired":{"data":True}}}}]}))
            with patch("companion.cli.Backend",return_value=app), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["mode","music"]),0)
            self.assertEqual(app.intent()["desired_mode"],"music")

    def test_cli_connection_dispatch(self):
        from companion.cli import main
        with patch("companion.cli.Backend") as factory,contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.connection.return_value={"connected":True}
            self.assertEqual(main(["connect"]),0)
            factory.return_value.connection.assert_called_once_with(True)

    def test_cli_voxtype_default_queues_without_probing_recording(self):
        from companion.cli import main
        with tempfile.TemporaryDirectory() as t:
            app=backend.Backend(Path(t),lambda args: "[]" if args[0]=="pw-dump" else '{"data":[{}]}')
            with patch("companion.cli.Backend",return_value=app),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["voxtype","default"]),0)
            self.assertEqual(app.intent()["voxtype"]["mode"],"default")

    def test_cli_policy_dispatch(self):
        from companion.cli import main
        with patch("companion.cli.Backend") as factory,contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.policy.return_value={}
            self.assertEqual(main(["policy","disable"]),0)
            self.assertEqual(factory.return_value.policy.call_count,1)

    def test_cli_watch_dispatch(self):
        from companion.cli import main
        with patch("companion.cli.Backend") as factory,contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.watch.return_value={}
            self.assertEqual(main(["watch","--iterations","1","--interval","0"]),0)
            self.assertEqual(factory.return_value.watch.call_count,1)

    def test_cli_apple_dispatch(self):
        from companion.cli import main
        with patch("companion.cli.Backend") as factory,contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.apple.return_value={}
            self.assertEqual(main(["apple","forget"]),0)
            self.assertEqual(factory.return_value.apple.call_count,1)

    def test_cli_select_device_dispatch(self):
        from companion.cli import main
        with patch("companion.cli.Backend") as factory,contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.select_device.return_value={}
            self.assertEqual(main(["select-device","invalid"]),0)
            self.assertEqual(factory.return_value.select_device.call_count,1)

    def test_cli_voxtype_run_dispatch(self):
        from companion.cli import main
        with patch("companion.cli.Backend") as factory:
            factory.return_value.run_voxtype.return_value=0
            self.assertEqual(main(["voxtype-run"]),0)
            factory.return_value.run_voxtype.assert_called_once_with()

    def test_invalid_selection_is_json_error_not_traceback(self):
        from companion.cli import main
        out=io.StringIO()
        with tempfile.TemporaryDirectory() as t,patch("companion.cli.Backend",return_value=backend.Backend(Path(t))),contextlib.redirect_stdout(out):
            self.assertEqual(main(["select-device","invalid"]),1)
        self.assertIn("Invalid Bluetooth",json.loads(out.getvalue())["error"])

    def test_cli_mutation_refuses_held_lock(self):
        from companion.cli import main
        with tempfile.TemporaryDirectory() as t:
            app=backend.Backend(Path(t))
            with app.exclusive(),patch("companion.cli.Backend",return_value=app),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["voxtype","default"]),1)

    def test_generated_pin_configuration_parses_with_real_libasound_without_capture(self):
        import ctypes, ctypes.util
        library=ctypes.util.find_library("asound")
        if library is None: self.skipTest("libasound unavailable")
        with tempfile.TemporaryDirectory() as t:
            app=backend.Backend(Path(t));app.save({"voxtype":{"mode":"pinned","source":"fixture.mic"}})
            _,_,config=app.voxtype_launch({})
            lib=ctypes.CDLL(library)
            ptr=ctypes.c_void_p;cfg=ptr();inp=ptr()
            lib.snd_config_top.argtypes=[ctypes.POINTER(ptr)]
            lib.snd_input_buffer_open.argtypes=[ctypes.POINTER(ptr),ctypes.c_char_p,ctypes.c_ssize_t]
            lib.snd_config_load.argtypes=[ptr,ptr]
            lib.snd_config_delete.argtypes=[ptr];lib.snd_input_close.argtypes=[ptr]
            self.assertEqual(lib.snd_config_top(ctypes.byref(cfg)),0)
            text=config.encode()
            self.assertEqual(lib.snd_input_buffer_open(ctypes.byref(inp),text,len(text)),0)
            try:
                self.assertEqual(lib.snd_config_load(cfg,inp),0)
            finally:
                lib.snd_input_close(inp);lib.snd_config_delete(cfg)
