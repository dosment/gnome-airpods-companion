import unittest, tempfile, json
from pathlib import Path
import companion.backend as b

MAC = "00:11:22:33:44:55"  # synthetic fixture
PATH = "/org/bluez/hci0/dev_00_11_22_33_44_55"
def bluez(connected=False):
    return {"data": [{PATH: {"org.bluez.Device1": {k: {"data": v} for k,v in {"Address": MAC, "Name": "Test AirPods", "Paired": True, "Connected": connected}.items()}}}]}
def graph(profile="a2dp-sink"):
    return [{"id":91,"type":"PipeWire:Interface:Device","info":{"props":{"device.api":"bluez5","api.bluez5.address":MAC},"params":{"Profile":[{"name":profile}],"EnumProfile":[{"index":1,"name":"a2dp-sink"},{"index":7,"name":"a2dp-sink-sbc_xq"},{"index":9,"name":"headset-head-unit-msbc"},{"index":10,"name":"headset-head-unit-lc3"}]}}}]
def sink():
    return {"id":92,"type":"PipeWire:Interface:Node","info":{"props":{"media.class":"Audio/Sink","device.id":91,"node.name":"bluez_output.test"}}}
class BackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.calls=[];self.pw=[];self.bz=bluez();self.setting=True;self.saved=None
        self.app=b.Backend(Path(self.tmp.name),self.run_command,sleeper=lambda _:None)
    def run_command(self,args):
        self.calls.append(args)
        if args[0]=="pw-dump": return json.dumps(self.pw)
        if args[0]=="busctl": return json.dumps(self.bz)
        if args[:2]==["wpctl","settings"]:
            if args[-1] in ("true","false"):
                self.setting=args[-1]=="true"
                if "--save" in args: self.saved=self.setting
            if "--delete" in args: self.saved=None
            return "Value: "+str(self.setting).lower()+(" (Saved: "+str(self.saved).lower()+")" if self.saved is not None else "")
        return ""
    def test_status_disconnected_is_read_only_and_preserves_no_intent(self):
        s=self.app.status()
        self.assertFalse(s["connected"]);self.assertEqual(s["device_name"],"Test AirPods")
        self.assertIsNone(s["desired_mode"]);self.assertEqual(s["voxtype"]["mode"],"default")
        self.assertEqual(list(Path(self.tmp.name).iterdir()),[])
        self.assertEqual([c[0] for c in self.calls],["pw-dump","busctl"])

    def test_bluez_discovery_falls_back_to_individual_device_properties(self):
        self.pw=[]
        values={"Address":MAC,"Name":"Test AirPods","Alias":"Test AirPods","Paired":True,"Connected":True}
        def fallback(args):
            self.calls.append(args)
            if args==["pw-dump"]:
                return "[]"
            if args==b.BLUEZ:
                raise RuntimeError("GetManagedObjects JSON unavailable")
            if args[:4]==["busctl","--system","tree","org.bluez"]:
                return "/\n/org/bluez/hci0\n"+PATH+"\n"+PATH+"/sep1\n"
            if "get-property" in args:
                return json.dumps({"type":"b" if isinstance(values[args[-1]],bool) else "s","data":values[args[-1]]})
            raise AssertionError(args)
        self.app.run=fallback
        status=self.app.status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["device_name"],"Test AirPods")
        self.assertIsNone(status["error"])

    def test_status_exposes_human_readable_active_profile_description(self):
        self.pw=graph("headset-head-unit");self.bz=bluez(True)
        self.pw[0]["info"]["params"]["Profile"][0]["description"]="Headset Head Unit (HSP/HFP, codec LC3-24kHz)"
        status=self.app.status()
        self.assertEqual(status["active_profile_description"],"Headset Head Unit (HSP/HFP, codec LC3-24kHz)")

    def test_mode_persists_disconnected_intent_without_switching(self):
        self.app.mode("meeting")
        self.assertEqual(self.app.intent()["desired_mode"],"meeting")
        self.assertEqual(self.app.intent()["device_address"],MAC)
        self.assertFalse(any(c[:2]==["wpctl","set-profile"] for c in self.calls))

    def test_meeting_selects_best_available_hfp_and_reads_actual_profile(self):
        self.pw=graph();self.bz=bluez(True)
        s=self.app.mode("meeting")
        self.assertIn(["wpctl","set-profile","91","10"],self.calls)
        self.assertEqual(s["active_profile"],"a2dp-sink")
        self.assertIn("not yet",s["error"])
        self.assertFalse(any("set-default" in c for c in self.calls))

    def test_mode_waits_for_delayed_pipewire_profile_readback(self):
        self.bz=bluez(True)
        reads=0
        def delayed(args):
            nonlocal reads
            self.calls.append(args)
            if args==["pw-dump"]:
                reads+=1
                return json.dumps(graph("a2dp-sink-sbc_xq" if reads >= 3 else "a2dp-sink"))
            if args[0]=="busctl":
                return json.dumps(self.bz)
            return ""
        self.app.run=delayed
        self.app.sleep=lambda _:None
        result=self.app.mode("music")
        self.assertIsNone(result["error"])
        self.assertEqual(result["active_profile"],"a2dp-sink-sbc_xq")
        self.assertGreaterEqual(reads,3)

    def test_mode_routes_only_the_live_airpods_output_node(self):
        self.pw=graph("headset-head-unit-lc3")+[sink()];self.bz=bluez(True)
        self.app.mode("meeting")
        self.assertIn(["wpctl","set-default","92"],self.calls)
        self.assertFalse(any(c[:2]==["wpctl","set-default"] and c[-1] != "92" for c in self.calls))

    def test_meeting_recognizes_lc3_codec_in_profile_description(self):
        self.pw=graph();self.bz=bluez(True)
        self.pw[0]["info"]["params"]["EnumProfile"] = [
            {"index":9,"name":"headset-head-unit-msbc","description":"Headset Head Unit (HSP/HFP, codec mSBC)","priority":5},
            {"index":10,"name":"headset-head-unit","description":"Headset Head Unit (HSP/HFP, codec LC3-24kHz)","priority":6},
        ]
        self.app.mode("meeting")
        self.assertIn(["wpctl","set-profile","91","10"],self.calls)

    def test_connect_targets_disconnected_paired_device_and_verifies(self):
        result=self.app.connection(True)
        self.assertIn(["busctl","--system","call","org.bluez",PATH,"org.bluez.Device1","Connect"],self.calls)
        self.assertIn("not yet", result["error"])

    def test_explicit_policy_enable_disable_restores_unsaved_setting(self):
        self.app.policy(True)
        self.assertFalse(self.setting);self.assertFalse(self.saved)
        self.assertTrue(self.app.intent()["policy"]["enabled"])
        self.app.policy(False)
        self.assertTrue(self.setting);self.assertIsNone(self.saved)
        self.assertFalse(self.app.intent()["policy"]["enabled"])

    def test_watch_is_opt_in_and_stops_fighting_after_three_attempts(self):
        self.pw=graph();self.bz=bluez(True)
        self.app.mode("meeting");self.calls.clear()
        self.app.watch(iterations=5, interval=0)
        self.assertFalse(any(c[:2]==["wpctl","set-profile"] for c in self.calls))
        self.app.policy(True);self.calls.clear()
        self.app.watch(iterations=11, interval=0)
        self.assertEqual(sum(c[:2]==["wpctl","set-profile"] for c in self.calls),3)
        self.assertEqual(self.app.watch_error,"Profile enforcement budget exhausted; explicit mode selection or reconnect required")

    def test_voxtype_pin_persists_only_intent_without_restart(self):
        self.pw=[{"info":{"props":{"media.class":"Audio/Source","node.name":"fixture.mic","node.description":"Test microphone"}}}]
        result=self.app.voxtype("fixture.mic")
        self.assertEqual(result["voxtype"]["source"],"fixture.mic")
        self.assertTrue(result["voxtype"]["pending_restart"])
        self.assertFalse(any(c[0]=="systemctl" for c in self.calls))
        self.app.voxtype(None)
        self.assertEqual(self.app.intent()["voxtype"]["mode"],"default")

    def test_voxtype_launch_uses_capture_only_alsa_pin_and_leaves_other_settings(self):
        self.app.save({"voxtype":{"mode":"pinned","source":"fixture.mic"}})
        args,env,config=self.app.voxtype_launch({"KEEP":"yes","PIPEWIRE_NODE":"old"})
        self.assertEqual(args,["voxtype","-q","--audio-device","pipewire","daemon"])
        self.assertIn('capture_node "fixture.mic"',config)
        self.assertNotIn("playback_node",config)
        self.assertNotIn("PIPEWIRE_NODE",env)
        self.assertEqual(env["KEEP"],"yes")
        self.app.save({})
        args,env,config=self.app.voxtype_launch({})
        self.assertIsNone(config)
        self.assertNotIn("ALSA_CONFIG_PATH",env)

    def test_apple_normalizes_actual_schema_without_inventing_capabilities(self):
        p=Path(self.tmp.name)/"librepods/status.json";p.parent.mkdir()
        p.write_text(json.dumps({"schema_version":1,"connected":False,"left":{"available":True,"level":63,"charging":False},"noise_mode":1}))
        a=self.app.status()["apple"]
        self.assertTrue(a["available"]);self.assertEqual(a["battery"]["left"]["level"],63)
        self.assertIsNone(a["battery"]["case"]["level"])
        self.assertEqual(a["controls"],[])
        p.write_text("{partial")
        self.assertFalse(self.app.status()["apple"]["available"])

    def test_apple_control_is_allowlisted_and_readback_is_not_assumed_success(self):
        raw={"schema_version":1,"connected":True,"supports_noise_control":True,"noise_mode":2}
        p=Path(self.tmp.name)/"librepods/status.json";p.parent.mkdir();p.write_text(json.dumps(raw))
        self.app.ctl=Path(self.tmp.name)/"librepods-ctl";self.app.ctl.touch()
        old=self.app.run
        self.app.run=lambda args: json.dumps(raw) if args==[str(self.app.ctl),"status"] else old(args)
        with self.assertRaises(ValueError): self.app.apple("forget")
        result=self.app.apple("noise:anc")
        self.assertFalse(result["confirmed"])
        self.assertIn([str(self.app.ctl),"noise:anc"],self.calls)

    def test_apple_control_waits_for_delayed_hardware_readback(self):
        before={"schema_version":1,"connected":True,"supports_noise_control":True,"noise_mode":2}
        after=dict(before,noise_mode=1)
        p=Path(self.tmp.name)/"librepods/status.json";p.parent.mkdir();p.write_text(json.dumps(before))
        self.app.ctl=Path(self.tmp.name)/"librepods-ctl";self.app.ctl.touch()
        reads=0
        def delayed(args):
            nonlocal reads
            self.calls.append(args)
            if args==[str(self.app.ctl),"status"]:
                reads+=1
                return json.dumps(after if reads >= 3 else before)
            return ""
        self.app.run=delayed
        self.app.sleep=lambda _:None
        result=self.app.apple("noise:anc")
        self.assertTrue(result["confirmed"])
        self.assertEqual(reads,3)

    def test_watch_routes_airpods_output_once_on_reconnect_generation(self):
        self.pw=graph("headset-head-unit-lc3")+[sink()];self.bz=bluez(True)
        self.setting=False;self.saved=False
        self.app.save({"desired_mode":"meeting","device_address":MAC,"mode_revision":"r1","policy":{"enabled":True,"previous":{"value":True,"saved":None}}})
        self.app.watch(iterations=1,interval=0)
        self.assertEqual(self.calls.count(["wpctl","set-default","92"]),1)

    def test_watch_bounds_ambiguous_output_route_failure_per_generation(self):
        self.pw=graph("headset-head-unit-lc3")+[sink()];self.bz=bluez(True)
        self.setting=False;self.saved=False
        self.app.save({"desired_mode":"meeting","device_address":MAC,"mode_revision":"r1","policy":{"enabled":True,"previous":{"value":True,"saved":None}}})
        route_calls=0
        def reply_lost_after_dispatch(args):
            nonlocal route_calls
            self.calls.append(args)
            if args==["pw-dump"]:
                return json.dumps(self.pw)
            if args[0]=="busctl":
                return json.dumps(self.bz)
            if args[:2]==["wpctl","settings"]:
                return "Value: false (Saved: false)"
            if args[:2]==["wpctl","set-default"]:
                route_calls+=1
                if route_calls == 1:
                    self.app.save({"desired_mode":"meeting","device_address":MAC,"mode_revision":"r2","policy":{"enabled":True,"previous":{"value":True,"saved":None}}})
                raise RuntimeError("reply lost after dispatch")
            return ""
        self.app.run=reply_lost_after_dispatch
        result=self.app.watch(iterations=5,interval=0)
        self.assertEqual(route_calls,2)
        self.assertEqual(result["error"],"reply lost after dispatch")

    def test_watch_routes_replacement_sink_from_confirming_graph(self):
        self.bz=bluez(True);self.setting=False;self.saved=False
        before=graph("a2dp-sink")+[sink()]
        replacement=sink();replacement["id"]=193
        after=graph("headset-head-unit-lc3")+[replacement]
        switched=False
        def replacing(args):
            nonlocal switched
            self.calls.append(args)
            if args==["pw-dump"]:
                return json.dumps(after if switched else before)
            if args[0]=="busctl":
                return json.dumps(self.bz)
            if args[:2]==["wpctl","settings"]:
                return "Value: false (Saved: false)"
            if args[:2]==["wpctl","set-profile"]:
                switched=True
            return ""
        self.app.run=replacing
        self.app.save({"desired_mode":"meeting","device_address":MAC,"mode_revision":"r1","policy":{"enabled":True,"previous":{"value":True,"saved":None}}})
        self.app.watch(iterations=1,interval=0)
        self.assertIn(["wpctl","set-default","193"],self.calls)
        self.assertNotIn(["wpctl","set-default","92"],self.calls)

    def test_watch_observes_and_routes_after_third_delayed_profile_write(self):
        self.bz=bluez(True);self.setting=False;self.saved=False
        before=graph("a2dp-sink")+[sink()]
        replacement=sink();replacement["id"]=193
        after=graph("headset-head-unit-lc3")+[replacement]
        writes=0;delayed_reads=0
        def delayed_third(args):
            nonlocal writes, delayed_reads
            self.calls.append(args)
            if args==["pw-dump"]:
                if writes == 3 and delayed_reads == 0:
                    return json.dumps(after)
                if writes == 3:
                    delayed_reads-=1
                return json.dumps(before)
            if args[0]=="busctl":
                return json.dumps(self.bz)
            if args[:2]==["wpctl","settings"]:
                return "Value: false (Saved: false)"
            if args[:2]==["wpctl","set-profile"]:
                writes+=1
                if writes == 3:
                    delayed_reads=1
            return ""
        self.app.run=delayed_third
        self.app.save({"desired_mode":"meeting","device_address":MAC,"mode_revision":"r1","policy":{"enabled":True,"previous":{"value":True,"saved":None}}})
        result=self.app.watch(iterations=4,interval=0)
        self.assertEqual(writes,3)
        self.assertIn(["wpctl","set-default","193"],self.calls)
        self.assertIsNone(result["error"])

    def test_watch_retains_target_when_third_dispatched_write_raises(self):
        self.bz=bluez(True);self.setting=False;self.saved=False
        before=graph("a2dp-sink")+[sink()]
        replacement=sink();replacement["id"]=193
        after=graph("headset-head-unit-lc3")+[replacement]
        writes=0;delayed_reads=0
        def raised_after_dispatch(args):
            nonlocal writes, delayed_reads
            self.calls.append(args)
            if args==["pw-dump"]:
                if writes == 3 and delayed_reads == 0:
                    return json.dumps(after)
                if writes == 3:
                    delayed_reads-=1
                return json.dumps(before)
            if args[0]=="busctl":
                return json.dumps(self.bz)
            if args[:2]==["wpctl","settings"]:
                return "Value: false (Saved: false)"
            if args[:2]==["wpctl","set-profile"]:
                writes+=1
                if writes == 3:
                    delayed_reads=1
                raise RuntimeError("set-profile result unavailable after dispatch")
            return ""
        self.app.run=raised_after_dispatch
        self.app.save({"desired_mode":"meeting","device_address":MAC,"mode_revision":"r1","policy":{"enabled":True,"previous":{"value":True,"saved":None}}})
        result=self.app.watch(iterations=5,interval=0)
        self.assertEqual(writes,3)
        self.assertIn(["wpctl","set-default","193"],self.calls)
        self.assertIsNone(result["error"])

    def test_watch_does_not_spend_retry_budget_when_profile_is_already_correct(self):
        self.pw=graph("headset-head-unit-lc3");self.bz=bluez(True)
        self.app.mode("meeting");self.app.policy(True)
        old=self.app.run;reads=0
        def drifting(args):
            nonlocal reads
            if args==["pw-dump"]:
                reads+=1
                if reads>8: self.pw=graph()
            return old(args)
        self.app.run=drifting;self.calls.clear()
        self.app.watch(iterations=12,interval=0)
        self.assertEqual(sum(c[:2]==["wpctl","set-profile"] for c in self.calls),3)

    def test_watch_reports_exhausted_profile_drift_after_output_was_routed(self):
        self.bz=bluez(True);self.setting=False;self.saved=False
        reads=0
        def drifting_after_route(args):
            nonlocal reads
            self.calls.append(args)
            if args==["pw-dump"]:
                reads+=1
                current=graph("headset-head-unit-lc3")+[sink()] if reads == 1 else graph("a2dp-sink")+[sink()]
                return json.dumps(current)
            if args[0]=="busctl":
                return json.dumps(self.bz)
            if args[:2]==["wpctl","settings"]:
                return "Value: false (Saved: false)"
            return ""
        self.app.run=drifting_after_route
        self.app.save({"desired_mode":"meeting","device_address":MAC,"mode_revision":"r1","policy":{"enabled":True,"previous":{"value":True,"saved":None}}})
        result=self.app.watch(iterations=12,interval=0)
        self.assertEqual(sum(c[:2]==["wpctl","set-profile"] for c in self.calls),3)
        self.assertEqual(result["error"],"Profile enforcement budget exhausted; explicit mode selection or reconnect required")

    def test_status_emits_contract_even_when_pipewire_is_unavailable(self):
        self.app.run=lambda args: (_ for _ in ()).throw(RuntimeError("probe unavailable"))
        s=self.app.status()
        self.assertEqual(s["schema_version"],1)
        self.assertIn("unavailable",s["error"])
        self.assertIsNone(s["active_profile"])

    def test_select_device_validates_address_and_pairing(self):
        with self.assertRaises(ValueError): self.app.select_device("bad")
        self.app.select_device(MAC)
        self.assertEqual(self.app.intent()["device_address"],MAC)

    def test_voxtype_runner_scopes_config_to_child_and_cleans_up(self):
        from unittest.mock import patch
        self.app.save({"voxtype":{"mode":"pinned","source":"fixture.mic"}})
        seen=[]
        self.assertEqual(self.app.status()["voxtype"].get("integration"),"unknown")
        app=self.app
        class Child:
            pid=__import__('os').getpid()
            def __init__(child,args,env):
                p=Path(env["ALSA_CONFIG_PATH"])
                self.assertIn('capture_node "fixture.mic"',p.read_text());seen.append(p)
            def wait(child):
                vox=app.status()["voxtype"]
                self.assertEqual(vox["effective"],{"mode":"pinned","source":"fixture.mic"})
                self.assertEqual(vox["integration"],"wrapper_running")
                self.assertFalse(vox["capture_verified"])
                self.assertFalse(vox["pending_restart"])
                app.voxtype(None)
                vox=app.status()["voxtype"]
                self.assertEqual(vox["effective"]["source"],"fixture.mic")
                self.assertTrue(vox["pending_restart"])
                return 0
        with patch.dict("os.environ",{},clear=True),patch("companion.backend.subprocess.Popen",side_effect=Child):
            self.assertEqual(self.app.run_voxtype(),0)
        self.assertFalse(seen[0].exists())
        self.assertIsNone(self.app.status()["voxtype"]["effective"])
        self.assertTrue(self.app.status()["voxtype"]["pending_restart"])

    def test_stale_voxtype_receipt_is_not_effective_routing(self):
        import os
        self.app.save({"voxtype":{"mode":"default","source":None,"pending_restart":False}})
        receipt=self.app.path.parent/"voxtype-launch.json"
        receipt.write_text(json.dumps({"pid":os.getpid(),"identity":"old-boot-or-reused-pid","routing":{"mode":"pinned","source":"old.mic"}}))
        vox=self.app.status()["voxtype"]
        self.assertIsNone(vox.get("effective"))
        self.assertEqual(vox.get("integration"),"stale_receipt")
        self.assertTrue(vox["pending_restart"])

    def test_watch_bounds_failed_subprocess_attempts(self):
        self.pw=graph();self.bz=bluez(True)
        self.app.mode("meeting");self.app.policy(True);self.calls.clear()
        old=self.app.run
        def failed(args):
            if args[:2]==["wpctl","set-profile"]:
                self.calls.append(args);raise RuntimeError("failed set-profile")
            return old(args)
        self.app.run=failed
        self.app.watch(iterations=9,interval=0)
        self.assertEqual(sum(c[:2]==["wpctl","set-profile"] for c in self.calls),3)

    def test_policy_reenable_does_not_overwrite_human_changes(self):
        self.app.policy(True)
        self.setting=True
        self.calls.clear()
        with self.assertRaises(RuntimeError): self.app.policy(True)
        self.assertFalse(any("--save" in c for c in self.calls))

    def test_status_keeps_desired_intent_when_probe_fails(self):
        self.app.save({"desired_mode":"meeting"})
        self.app.run=lambda args: (_ for _ in ()).throw(RuntimeError("offline"))
        self.assertEqual(self.app.status()["desired_mode"],"meeting")

    def test_apple_schema_matches_native_frontend_capability_contract(self):
        a=self.app.normalize_apple({"connected":True,"supports_noise_control":True,"supports_adaptive":True,"supports_conversational_awareness":True,"supports_one_bud_anc":True,"noise_mode":3,"ear_detection_behavior":0,"adaptive_noise_level":40})
        self.assertEqual(a["capabilities"]["noise_modes"],["anc","transparency","adaptive"])
        self.assertTrue(a["capabilities"]["adaptive_level"])
        self.assertEqual(a["state"]["noise_mode"],"adaptive")
        self.assertTrue(a["capabilities"]["ear_detection"])

    def test_adaptive_control_accepts_only_exact_integer_in_supported_mode(self):
        raw={"schema_version":1,"connected":True,"supports_adaptive":True,"noise_mode":3,"adaptive_noise_level":40}
        p=Path(self.tmp.name)/"librepods/status.json";p.parent.mkdir();p.write_text(json.dumps(raw))
        self.app.ctl=Path(self.tmp.name)/"librepods-ctl";self.app.ctl.touch()
        self.app.run=lambda args: json.dumps(raw)
        result=self.app.apple("adaptive:40")
        self.assertIsNone(result["confirmed"])
        self.assertTrue(result["reported_matches"])
        self.assertEqual(result["confirmation_scope"],"daemon_preference")
        with self.assertRaises(ValueError): self.app.apple("adaptive:040")
        with self.assertRaises(ValueError): self.app.apple("adaptive:101")

    def test_preference_readback_is_not_a_hardware_ack_and_ear_is_local_policy(self):
        raw={"schema_version":1,"connected":True,"supports_conversational_awareness":True,"supports_one_bud_anc":True,"conversational_awareness":True,"one_bud_anc_mode":True,"ear_detection_behavior":0}
        p=Path(self.tmp.name)/"librepods/status.json";p.parent.mkdir();p.write_text(json.dumps(raw))
        self.app.ctl=Path(self.tmp.name)/"librepods-ctl";self.app.ctl.touch()
        self.app.run=lambda args: json.dumps(raw)
        for verb in ("ca:on","onebud:on"):
            result=self.app.apple(verb)
            self.assertIsNone(result["confirmed"])
            self.assertTrue(result["reported_matches"])
            self.assertEqual(result["confirmation_scope"],"daemon_preference")
        result=self.app.apple("ear:one")
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["confirmation_scope"],"local_policy")
        self.assertEqual(result["apple"].get("state_sources"),{
            "noise_mode":"hardware_observation","conversation_awareness":"daemon_preference",
            "one_bud_anc":"daemon_preference","adaptive_level":"daemon_preference","ear_detection":"local_policy"})

    def test_watch_rejects_unbounded_zero_interval(self):
        with self.assertRaises(ValueError): self.app.watch(interval=0)
        with self.assertRaises(ValueError): self.app.watch(iterations=-1)

    def test_malformed_saved_intent_is_reported_without_unsafe_mode(self):
        self.app.save({"desired_mode":"surprise"})
        s=self.app.status()
        self.assertIn("intent",s["error"])
        self.assertIsNone(s["desired_mode"])

    def test_mutation_lock_refuses_overlapping_ownership(self):
        with self.app.exclusive():
            with self.assertRaises(RuntimeError):
                with self.app.exclusive(): pass
        with self.app.exclusive(): pass

    def test_watcher_does_not_race_explicit_mutations(self):
        self.pw=graph();self.bz=bluez(True)
        self.app.mode("meeting");self.app.policy(True);self.calls.clear()
        with self.app.exclusive():
            self.app.watch(iterations=1,interval=0)
        self.assertFalse(any(c[:2]==["wpctl","set-profile"] for c in self.calls))

    def test_unrelated_voxtype_intent_does_not_reset_profile_fighting_budget(self):
        self.pw=graph();self.bz=bluez(True)
        self.app.mode("meeting");self.app.policy(True);self.calls.clear()
        old=self.app.run
        def changing(args):
            if args==["pw-dump"]:
                intent=self.app.intent();intent["voxtype"]={"mode":"default","source":None};self.app.save(intent)
            return old(args)
        self.app.run=changing
        self.app.watch(iterations=9,interval=0)
        self.assertEqual(sum(c[:2]==["wpctl","set-profile"] for c in self.calls),3)

    def test_explicit_reselection_updates_only_mode_revision(self):
        self.app.mode("meeting");first=self.app.intent().get("mode_revision")
        self.assertIsNotNone(first)
        self.app.mode("meeting")
        self.assertNotEqual(self.app.intent()["mode_revision"],first)

    def test_malformed_pipewire_graph_is_a_structured_error(self):
        self.pw={"unexpected":"shape"}
        self.assertIn("PipeWire",self.app.status()["error"])

    def test_music_prefers_enumerated_sbc_xq(self):
        self.pw=graph();self.bz=bluez(True)
        self.app.mode("music")
        self.assertIn(["wpctl","set-profile","91","7"],self.calls)

    def test_unavailable_profiles_are_not_selected_and_intent_is_retained(self):
        self.pw=graph();self.bz=bluez(True)
        for p in self.pw[0]["info"]["params"]["EnumProfile"]:
            if p["name"].startswith("headset"): p["available"]="no"
        with self.assertRaises(ValueError): self.app.mode("meeting")
        self.assertEqual(self.app.intent()["desired_mode"],"meeting")
        self.assertFalse(any(c[:2]==["wpctl","set-profile"] for c in self.calls))

    def test_policy_restores_distinct_saved_and_runtime_values(self):
        self.saved=True;self.setting=False
        self.app.policy(True);self.app.policy(False)
        self.assertTrue(self.saved);self.assertFalse(self.setting)

    def test_apple_old_snapshot_is_stale_without_inventing_battery(self):
        import os,time
        p=Path(self.tmp.name)/"librepods/status.json";p.parent.mkdir()
        p.write_text(json.dumps({"schema_version":1,"connected":True,"supports_noise_control":True,"left":{"available":True,"level":True}}))
        os.utime(p,(time.time()-400,time.time()-400))
        a=self.app.apple_status()
        self.assertTrue(a["stale"]);self.assertEqual(a["controls"],[])
        self.assertFalse(a["battery"]["left"]["available"])

    def test_old_write_on_change_snapshot_checks_installed_daemon_liveness(self):
        import os, time
        raw={"schema_version":1,"connected":True,"supports_noise_control":True,"left":{"available":True,"level":63}}
        p=Path(self.tmp.name)/"librepods/status.json";p.parent.mkdir();p.write_text(json.dumps(raw))
        os.utime(p,(time.time()-600,time.time()-600))
        self.app.ctl=Path(self.tmp.name)/"librepods-ctl";self.app.ctl.touch()
        def reply(args):
            self.calls.append(args)
            return json.dumps(raw)
        self.app.run=reply
        a=self.app.apple_status()
        self.assertFalse(a["stale"])
        self.assertEqual(a["liveness"],"responsive")
        self.assertIn("noise:anc",a["controls"])
        self.assertEqual(a["battery"]["left"]["freshness"],"unknown")
        self.assertEqual(self.calls,[[str(self.app.ctl),"status"]])
        self.app.run=lambda args: (_ for _ in ()).throw(RuntimeError("timeout"))
        a=self.app.apple_status()
        self.assertTrue(a["stale"])
        self.assertEqual(a["controls"],[])
        self.assertEqual(a["battery"]["left"]["level"],63)

    def test_subprocess_boundary_has_timeout_and_never_uses_shell(self):
        from unittest.mock import patch
        import subprocess
        with patch("companion.backend.subprocess.run",side_effect=subprocess.TimeoutExpired("pw-dump",12)) as run:
            with self.assertRaises(RuntimeError): b.command(["pw-dump"])
            self.assertEqual(run.call_args.kwargs["timeout"],12)
            self.assertNotIn("shell",run.call_args.kwargs)
