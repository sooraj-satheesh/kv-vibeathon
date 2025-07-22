# **Sherlock: The Screen Annotator with LLM Assistant**

A PyQt6 application for capturing screen selections, annotating them with various tools, and interacting with an integrated LLM chatbot.

## **Key Features**

* **Full-Screen Screenshot Capture:** Easily capture your entire screen to begin annotation.  
* **Freestyle Selection:** Define a custom area of interest using a freehand drawing selection.  
* **Multiple Annotation Modes:**  
  * **Freestyle:** Draw freehand lines.  
  * **Rectangle:** Draw rectangular shapes.  
  * **Arrow:** Draw directional arrows.  
  * **Text:** Add custom text labels.  
  * **Blur:** Apply a blur effect to selected areas.  
  * **Highlight:** Highlight areas with a semi-transparent yellow.  
  * **Erase:** Erase annotations.  
* **Undo Functionality:** Revert the last annotation action.  
* **Dynamic UI:** Annotation tools and chat interface appear contextually after selection.  
* **Animated Visuals:**  
  * Full-screen animated background gradient (red and blue).  
  * Rotating red-grey-blue gradient border with rounded corners around the selected area.  
  * LLM "thinking" animation during chatbot responses.  
* **Integrated LLM Chatbot:**  
  * Send text messages and the current annotated image to an LLM (powered by litellm).  
  * Receive streaming responses from the LLM displayed in real-time.  
  * Chat history is maintained for context.

## **Technologies Used**

* **Python 3**  
* **PyQt6:** For the graphical user interface.  
* **Pillow (PIL):** For image manipulation (screenshot capture, blurring).  
* **litellm:** To simplify LLM API calls and enable streaming.  
* **markdown:** To render markdown content from LLM responses in the chat display.

## **Setup Instructions**

To set up and run this application, follow these steps:

1. Ensure Python is Installed:  
   Make sure you have Python 3.8 or higher installed on your system. You can download it from python.org.  
2. Create a Virtual Environment (Recommended):  
   Open your terminal or command prompt and run:  
   python \-m venv venv

3. **Activate the Virtual Environment:**  
   * **On Windows:**  
     .\\venv\\Scripts\\activate

   * **On macOS/Linux:**  
     source venv/bin/activate

4. Install Dependencies:

   Install the required Python packages using pip:  
   pip install \-r requirements.txt

5. Run the Application:  
   Navigate to the directory containing the screenshot\_annotator.py file and run:  
   python screenshot\_annotator.py

   The application will launch in full-screen mode, allowing you to select an area of your screen for annotation and interact with the chatbot.