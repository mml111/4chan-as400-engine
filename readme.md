4CHAN AS/400 Terminal Engine
A retro, text-based terminal experience that bridges the modern web with legacy enterprise workstations. This application acts as a text-mode 4chan imageboard browser designed specifically to mimic the look, feel, and navigational constraints of an IBM AS/400 (System i) minicomputer console.

System Features
IBM 5250 Emulation UI: Renders standard AS/400 menus, headers, function-key navigation footers, and system status lines.

Aspect-Ratio-Locked Terminal Imaging: Translates 4chan thumbnails into dense TrueColor half-block (▀) graphics dynamically scaled to fit perfectly within terminal boundary constraints.

Dual-Pane Media & QR Spooling: When inspecting an image, the system displays the visual asset side-by-side with a generated ANSI QR code pointing to the raw external file URL.

Asynchronous Networking: Built on telnetlib3 and httpx to deliver highly responsive screen refreshes.

Prerequisites
Ensure you have the following installed on your machine:

Python 3.8+

pip (Python package installer)

Installation & Setup
Clone the repository:

Bash
git clone https://github.com/your-username/4chan-as400-engine.git
cd 4chan-as400-engine
(Optional but Recommended) Create a Virtual Environment:

Bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
Install dependencies:

Bash
pip install -r requirements.txt
Run the server:

Bash
python 4chanas400.py
The console will confirm that the subsystem is operational and bound to a local TCP Telnet port (default: 2324).

Usage & Navigation
Connect to your local instance using any standard Telnet client (e.g., PuTTY, Telnet, or terminal CLI) pointing to localhost on port 2324.

Command Reference
GO <board> (or simply 1 for the default board): Navigate to an imageboard catalog (e.g., GO g, GO sci).

VIEW <option_number>: Select a thread from the catalog list to view the OP along with replies and text conversations.

IMG <number>: Render an ASCII/ANSI half-block visualization of the image attached to a post.

+ / -: Page forward or backward through catalog listings and long threads.

F3 / EXIT (or 90): Terminate the session and exit the mainframe console.

Project Structure
Plaintext
4chan-as400-engine/
├── 4chanas400.py         # Main execution script running the telnet/async server
├── requirements.txt      # Required Python libraries and dependencies
└── README.md             # Project documentation and usage guide
License
Distributed under the MIT License. See LICENSE for more information.