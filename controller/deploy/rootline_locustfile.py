# Rootline's load: the demo's own locustfile minus one task.
#
# Demo 3.1.0's WebsiteUser.ask_agent posts to the `agent` service, which only
# compose.agent.yaml starts. Rootline does not run it, so every call failed
# with a DNS error and those failed traces filled the top of every snapshot's
# trace evidence. compose.override.yml mounts this file next to the demo's
# locustfile.py and points LOCUST_LOCUSTFILE at it.
import locustfile as demo
from locustfile import *  # noqa: F401,F403  (Locust picks up the User classes from here)

demo.WebsiteUser.tasks = [
    t for t in demo.WebsiteUser.tasks if getattr(t, "__name__", "") != "ask_agent"
]
