"""Read-only discovery and explicitly requested audio policy. No global source writes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile

BLUEZ = ["busctl", "--system", "--json=short", "call", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"]

def command(args):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=12).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Command failed: " + args[0]) from exc

class Backend:
    def __init__(self, state_home=None, run=command):
        self.home = Path(state_home or os.environ.get("XDG_STATE_HOME", str(Path.home()/".local/state")))
        self.path = self.home / "gnome-airpods-companion/intent.json"
        self.run = run

    def intent(self):
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text())
        if not isinstance(value, dict) or value.get("desired_mode") not in (None,"music","meeting"):
            raise ValueError("Invalid intent file")
        routing = value.get("voxtype",{"mode":"default","source":None})
        if not isinstance(routing,dict) or routing.get("mode") not in ("default","pinned") or (routing.get("mode") == "pinned" and not isinstance(routing.get("source"),str)):
            raise ValueError("Invalid Voxtype intent")
        if not isinstance(value.get("policy",{}),dict):
            raise ValueError("Invalid policy intent")
        return value

    def discover(self):
        graph = json.loads(self.run(["pw-dump"]))
        if not isinstance(graph,list) or any(not isinstance(x,dict) for x in graph):
            raise ValueError("Invalid PipeWire graph")
        raw = json.loads(self.run(BLUEZ))["data"][0]
        devices = []
        for path, interfaces in raw.items():
            props = interfaces.get("org.bluez.Device1", {})
            p = {k: v["data"] for k, v in props.items()}
            if p.get("Paired") and "airpods" in p.get("Name", "").lower():
                devices.append(dict(p, path=path))
        selected = self.intent().get("device_address")
        matches = [d for d in devices if d.get("Address") == selected] if selected else devices
        if len(matches) > 1:
            raise ValueError("Multiple paired AirPods; select-device ADDRESS first")
        device = matches[0] if matches else None
        card = next((x for x in graph if x.get("type") == "PipeWire:Interface:Device" and device and x.get("info",{}).get("props",{}).get("api.bluez5.address") == device["Address"]), None)
        return graph, device, card

    def status(self):
        error = None
        intent = {}
        try:
            intent = self.intent()
            graph, device, card = self.discover()
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            graph, device, card = [], None, None
            error = str(exc)
        profiles = card.get("info",{}).get("params",{}).get("Profile",[]) if card else []
        microphones = []
        for obj in graph:
            p = obj.get("info",{}).get("props",{})
            if p.get("media.class") == "Audio/Source" and p.get("node.name"):
                microphones.append({"name":p["node.name"],"description":p.get("node.description",p["node.name"])})
        return {"schema_version":1,"connected":bool(device and device.get("Connected")),"device_name":device.get("Alias",device.get("Name")) if device else None,"desired_mode":intent.get("desired_mode"),"active_profile":profiles[0].get("name") if profiles else None,"error":error,"microphones":microphones,"voxtype":self.voxtype_status(intent),"apple":self.apple_status()}

    def save(self, value, path=None):
        path = path or self.path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def mode(self, mode):
        if mode not in ("music", "meeting"):
            raise ValueError("Invalid mode")
        _, device, card = self.discover()
        if not device:
            raise ValueError("No selected paired AirPods")
        intent = self.intent()
        import uuid
        intent.update(desired_mode=mode, device_address=device["Address"], mode_revision=uuid.uuid4().hex)
        self.save(intent)
        target = self.apply(card, mode) if card else None
        result = self.status()
        if target and result["active_profile"] != target:
            result["error"] = "Desired profile not yet observed"
        return result

    def apply(self, card, mode):
        profiles = card["info"].get("params",{}).get("EnumProfile",[])
        prefix = "a2dp-sink" if mode == "music" else "headset-head-unit"
        choices = [p for p in profiles if p.get("name", "").startswith(prefix) and p.get("available") not in ("no", False) and isinstance(p.get("index"), int)]
        if not choices:
            raise ValueError("Requested profile unavailable")
        def rank(p):
            name = p["name"].lower()
            if mode == "music":
                return ("sbc_xq" in name, p.get("priority",0))
            return (3 if "lc3" in name else 2 if "msbc" in name else 1, p.get("priority",0))
        target = max(choices, key=rank)
        active = card["info"].get("params",{}).get("Profile",[])
        if not active or active[0].get("name") != target["name"]:
            self.run(["wpctl","set-profile",str(card["id"]),str(target["index"])])
        return target["name"]

    def connection(self, connect):
        _, device, _ = self.discover()
        if not device:
            raise ValueError("No selected paired AirPods")
        intent = self.intent()
        intent["device_address"] = device["Address"]
        self.save(intent)
        self.run(["busctl","--system","call","org.bluez",device["path"],"org.bluez.Device1","Connect" if connect else "Disconnect"])
        result = self.status()
        if result["connected"] != connect:
            result["error"] = "Requested connection state not yet observed"
        return result

    def setting(self):
        import re
        text = self.run(["wpctl","settings","bluetooth.autoswitch-to-headset-profile"])
        current = re.search(r"Value:\s*(true|false)", text)
        saved = re.search(r"Saved:\s*(true|false)", text)
        if not current:
            raise ValueError("Cannot read WirePlumber autoswitch setting")
        return {"value":current[1] == "true", "saved": saved[1] == "true" if saved else None}

    def policy(self, enabled):
        intent = self.intent()
        owned = intent.get("policy",{})
        key = "bluetooth.autoswitch-to-headset-profile"
        current = self.setting()
        if enabled:
            if owned.get("enabled") and current != {"value":False,"saved":False}:
                raise RuntimeError("Autoswitch changed externally; refusing to overwrite human edit")
            if not owned.get("enabled"):
                owned = {"enabled":True,"previous":current}
                intent["policy"] = owned
                self.save(intent)  # journal before changing external state
            self.run(["wpctl","settings","--save",key,"false"])
            if self.setting() != {"value":False,"saved":False}:
                raise RuntimeError("Autoswitch disable not observed")
        elif owned.get("enabled"):
            if current != {"value":False,"saved":False}:
                raise RuntimeError("Autoswitch changed externally; preserve human edit and resolve ownership manually")
            previous = owned["previous"]
            if previous["saved"] is None:
                self.run(["wpctl","settings","--delete",key])
            else:
                self.run(["wpctl","settings","--save",key,str(previous["saved"]).lower()])
            self.run(["wpctl","settings",key,str(previous["value"]).lower()])
            if self.setting() != previous:
                raise RuntimeError("Autoswitch restoration not observed")
            owned["enabled"] = False
            self.save(intent)
        return {"policy":owned,"autoswitch":self.setting()}

    def watch(self, iterations=None, interval=2.0):
        import time
        import math
        if not math.isfinite(interval) or interval < 0 or (iterations is None and interval < 0.5) or (iterations is not None and not 0 <= iterations <= 100000):
            raise ValueError("Watch requires finite interval >= 0.5s unless bounded, and nonnegative bounded iterations")
        generation = None
        attempts = 0
        self.watch_error = None
        count = 0
        while iterations is None or count < iterations:
            count += 1
            try:
                with self.exclusive():
                    intent = self.intent()
                    if intent.get("policy",{}).get("enabled") and intent.get("desired_mode"):
                        _, device, card = self.discover()
                        token = (device["Address"], card["info"].get("props",{}).get("object.serial",card["id"]), intent.get("mode_revision",intent["desired_mode"])) if card and device and device.get("Connected") else None
                        if token != generation:
                            generation, attempts = token, 0
                            self.watch_error = None
                        if token and attempts < 3:
                            if self.setting()["value"]:
                                self.watch_error = "Autoswitch changed externally; enforcement paused"
                            else:
                                active = card["info"].get("params",{}).get("Profile",[])
                                attempts += 1  # failures consume budget too
                                target = self.apply(card, intent["desired_mode"])
                                if active and active[0].get("name") == target:
                                    attempts -= 1
                                observed = self.status()
                                if observed["active_profile"] != target and attempts == 3:
                                    self.watch_error = "Profile enforcement budget exhausted; explicit mode selection or reconnect required"
                        elif token and attempts >= 3:
                            self.watch_error = "Profile enforcement budget exhausted; explicit mode selection or reconnect required"
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                self.watch_error = str(exc)
            if iterations is None or count < iterations:
                time.sleep(interval)
        return {"error":self.watch_error}

    def voxtype(self, source):
        if source is not None:
            import re
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,512}",source):
                raise ValueError("Unsafe PipeWire source name")
            if source not in [m["name"] for m in self.status()["microphones"]]:
                raise ValueError("Pinned microphone is not currently available")
        intent = self.intent()
        intent["voxtype"] = {"mode":"pinned" if source else "default","source":source,"pending_restart":True}
        self.save(intent)
        return self.status()

    def voxtype_launch(self, environ):
        # This is a launch-time snapshot, never an edit to a running daemon.
        env = dict(environ)
        if "ALSA_CONFIG_PATH" in env or "PIPEWIRE_ALSA" in env:
            raise ValueError("Existing per-process ALSA overrides require manual integration")
        env.pop("PIPEWIRE_NODE",None)
        routing = self.intent().get("voxtype",{})
        config = None
        if routing.get("mode") == "pinned":
            import re
            source = routing.get("source","")
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,512}",source):
                raise ValueError("Unsafe PipeWire source name")
            config = '</usr/share/alsa/alsa.conf>\npcm.!pipewire {\n type pipewire\n capture_node "' + source + '"\n hint { show on description "Companion PipeWire input" }\n}\n'
        return ["voxtype","-q","--audio-device","pipewire","daemon"], env, config

    def apple_status(self):
        import time
        path = self.home / "librepods/status.json"
        try:
            if path.stat().st_size > 65536:
                raise ValueError("Apple status exceeds size limit")
            raw = json.loads(path.read_text())
            if not isinstance(raw,dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1 or type(raw.get("connected")) is not bool:
                raise ValueError("Unsupported Apple status schema")
            age = max(0,time.time()-path.stat().st_mtime)
            result = self.normalize_apple(raw)
            result.update(age_seconds=round(age,1), stale=age>300, liveness="recent_snapshot")
            # A write-on-change snapshot is not a heartbeat. Probe only our installed ctl.
            if result["stale"]:
                result["liveness"] = "unknown"
                try:
                    ctl = getattr(self,"ctl",Path(__file__).resolve().parents[1]/"libexec/librepods-ctl")
                    if not ctl.is_file():
                        raise ValueError("Pinned librepods-ctl not installed")
                    live = json.loads(self.run([str(ctl),"status"]))
                    if not isinstance(live,dict) or type(live.get("schema_version")) is not int or live["schema_version"] != 1 or type(live.get("connected")) is not bool:
                        raise ValueError("Invalid Apple liveness reply")
                    result = self.normalize_apple(live)
                    result.update(age_seconds=round(age,1), stale=False, liveness="responsive")
                except (OSError,ValueError,TypeError,RuntimeError) as exc:
                    result.update(controls=[], error=str(exc))
            return result
        except (OSError,ValueError,TypeError) as exc:
            return {"available":False,"stale":True,"controls":[],"error":str(exc) if path.exists() else "Apple bridge not available"}

    def normalize_apple(self, raw):
        result = {"available":True,"connected":raw["connected"],"battery":{},"capabilities":{},"controls":[],"noise_mode":raw.get("noise_mode"),"ear_detection_behavior":raw.get("ear_detection_behavior"),"conversational_awareness":raw.get("conversational_awareness"),"one_bud_anc_mode":raw.get("one_bud_anc_mode"),"adaptive_noise_level":raw.get("adaptive_noise_level")}
        for part in ("left","right","case"):
            value = raw.get(part,{})
            if not isinstance(value,dict):
                value = {}
            level = value.get("level")
            available = value.get("available") is True and type(level) is int and 0 <= level <= 100
            result["battery"][part] = {"freshness":"unknown","available":available,"level":level if available else None,"charging":value.get("charging") if type(value.get("charging")) is bool else None,"in_ear":value.get("in_ear") if type(value.get("in_ear")) is bool else None}
        for key in ("supports_noise_control","supports_noise_off","supports_adaptive","supports_conversational_awareness","supports_one_bud_anc"):
            result["capabilities"][key] = raw.get(key) if type(raw.get(key)) is bool else None
        if raw["connected"]:
            controls = result["controls"]
            if raw.get("supports_noise_control") is True:
                controls.extend(["noise:anc","noise:transparency"])
                if raw.get("supports_noise_off") is True:
                    controls.append("noise:off")
            if raw.get("supports_adaptive") is True:
                controls.append("noise:adaptive")
            if raw.get("supports_conversational_awareness") is True:
                controls.extend(["ca:on","ca:off"])
            if raw.get("supports_one_bud_anc") is True:
                controls.extend(["onebud:on","onebud:off"])
            if type(raw.get("ear_detection_behavior")) is int and raw["ear_detection_behavior"] in (0,1,2):
                controls.extend(["ear:one","ear:both","ear:off"])
        cap = result["capabilities"]
        cap["noise_modes"] = [v.split(":")[1] for v in result["controls"] if v.startswith("noise:")]
        cap["conversation_awareness"] = "ca:on" in result["controls"]
        cap["one_bud_anc"] = "onebud:on" in result["controls"]
        cap["ear_detection"] = "ear:one" in result["controls"]
        cap["adaptive_level"] = raw.get("supports_adaptive") is True and type(raw.get("adaptive_noise_level")) is int and 0 <= raw["adaptive_noise_level"] <= 100
        result["state"] = {"noise_mode":{0:"off",1:"anc",2:"transparency",3:"adaptive"}.get(raw.get("noise_mode")),"conversation_awareness":raw.get("conversational_awareness"),"one_bud_anc":raw.get("one_bud_anc_mode"),"ear_detection":{0:"one",1:"both",2:"off"}.get(raw.get("ear_detection_behavior")),"adaptive_level":raw.get("adaptive_noise_level")}
        result["state_sources"] = {"noise_mode":"hardware_observation","conversation_awareness":"daemon_preference","one_bud_anc":"daemon_preference","adaptive_level":"daemon_preference","ear_detection":"local_policy"}
        return result

    def apple(self, verb):
        before = self.apple_status()
        import re
        adaptive = re.fullmatch(r"adaptive:(0|[1-9][0-9]?|100)",verb)
        allow_adaptive = adaptive and before.get("connected") is True and before.get("stale") is False and before.get("capabilities",{}).get("adaptive_level") is True and before.get("state",{}).get("noise_mode") == "adaptive"
        if verb not in before.get("controls",[]) and not allow_adaptive:
            raise ValueError("Apple control unsupported, unavailable, or stale")
        ctl = getattr(self,"ctl",Path(__file__).resolve().parents[1]/"libexec/librepods-ctl")
        if not ctl.is_file():
            raise ValueError("Pinned librepods-ctl not installed in companion libexec")
        self.run([str(ctl),verb])
        raw = json.loads(self.run([str(ctl),"status"]))
        if not isinstance(raw,dict) or raw.get("schema_version") != 1 or type(raw.get("connected")) is not bool:
            raise ValueError("Invalid Apple control readback")
        expected = {"noise:off":("noise_mode",0),"noise:anc":("noise_mode",1),"noise:transparency":("noise_mode",2),"noise:adaptive":("noise_mode",3),"ear:one":("ear_detection_behavior",0),"ear:both":("ear_detection_behavior",1),"ear:off":("ear_detection_behavior",2),"ca:on":("conversational_awareness",True),"ca:off":("conversational_awareness",False),"onebud:on":("one_bud_anc_mode",True),"onebud:off":("one_bud_anc_mode",False)}
        key, value = ("adaptive_noise_level",int(adaptive[1])) if adaptive else expected[verb]
        matches = raw.get(key) == value and type(raw.get(key)) is type(value)
        scope = "hardware_observation" if verb.startswith("noise:") else "local_policy" if verb.startswith("ear:") else "daemon_preference"
        confirmed = matches if scope != "daemon_preference" else None
        return {"apple":self.normalize_apple(raw),"confirmed":confirmed,"reported_matches":matches,"confirmation_scope":scope,"error":None if matches else "Requested Apple value not yet reported"}

    def select_device(self, address):
        import re
        if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", address):
            raise ValueError("Invalid Bluetooth address")
        raw = json.loads(self.run(BLUEZ))["data"][0]
        if not any(p.get("Address",{}).get("data") == address and p.get("Paired",{}).get("data") is True and "airpods" in p.get("Name",{}).get("data", "").lower() for interfaces in raw.values() for p in [interfaces.get("org.bluez.Device1",{})]):
            raise ValueError("Address is not a known paired AirPods device")
        intent = self.intent()
        intent["device_address"] = address
        self.save(intent)
        return self.status()

    @staticmethod
    def process_identity(pid):
        if type(pid) is not int or pid <= 0:
            return None
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()
            if fields[0] in ("Z","X"):
                return None
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip() + ":" + fields[19]
        except (OSError,IndexError):
            return None

    def voxtype_status(self, intent):
        desired = dict(intent.get("voxtype",{"mode":"default","source":None}))
        effective = None
        integration = "unknown"
        path = self.path.parent/"voxtype-launch.json"
        if path.exists():
            integration = "stale_receipt"
            try:
                receipt = json.loads(path.read_text())
                identity = self.process_identity(receipt.get("pid"))
                owner = self.process_identity(receipt.get("owner_pid"))
                if identity and identity == receipt.get("identity") and owner and owner == receipt.get("owner_identity"):
                    effective = receipt["routing"]
                    integration = "wrapper_running"
            except (OSError,ValueError,TypeError,AttributeError,KeyError):
                pass
        desired.update(effective=effective, integration=integration, capture_verified=False,
                       pending_restart=effective != {"mode":desired["mode"],"source":desired.get("source")})
        return desired

    def run_voxtype(self):
        # Supervise only this child; systemd's default KillMode=control-group
        # delivers stop signals to it as well. Never start/restart an existing service.
        with tempfile.TemporaryDirectory(prefix="companion-voxtype-") as directory:
            receipt_path = self.path.parent/"voxtype-launch.json"
            with self.exclusive():
                args, env, config = self.voxtype_launch(os.environ)
                intent = self.intent()
                routing = intent.get("voxtype",{"mode":"default","source":None})
                snapshot = {"mode":routing["mode"],"source":routing.get("source")}
                if config:
                    path = Path(directory)/"alsa.conf"
                    path.write_text(config)
                    path.chmod(0o600)
                    env["ALSA_CONFIG_PATH"] = str(path)
                child = subprocess.Popen(args,env=env)
                try:
                    self.save({"pid":child.pid,"identity":self.process_identity(child.pid),
                               "owner_pid":os.getpid(),"owner_identity":self.process_identity(os.getpid()),
                               "routing":snapshot}, receipt_path)
                    intent["voxtype"] = dict(snapshot,pending_restart=False)
                    self.save(intent)
                except BaseException:
                    child.terminate()
                    child.wait()
                    receipt_path.unlink(missing_ok=True)
                    raise
            try:
                return child.wait()
            finally:
                receipt_path.unlink(missing_ok=True)

    @contextmanager
    def exclusive(self, name="mutation"):
        import fcntl
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd = os.open(self.path.parent/(name+".lock"),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"w") as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another companion operation owns the "+name+" lock") from exc
            yield
