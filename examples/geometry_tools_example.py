# FILE: examples/geometry_tools_example.py

# --- 1. Imports and Configuration ---
import os
import json
import logging
import re
import time
from typing import Dict, Any, Optional

# Our observability module
from kansatsu import Kansatsu

# Third-party libraries for this example
import vertexai
from vertexai.generative_models import GenerativeModel
from opentelemetry import trace

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    # For this example to work, you must be authenticated with Google Cloud.
    # The simplest way is to run `gcloud auth application-default login` in your terminal.
    GCP_PROJECT_ID = '<your-gcp-project-id>'  # <--- CHANGE THIS
    GCP_LOCATION = '<your-location>'    # <--- CHANGE THIS
    GEMINI_MODEL_NAME = 'gemini-2.5-flash' # Using Flash for speed and cost
    logging.info("✅ Configuration loaded. Make sure you are authenticated with gcloud.")
except Exception as e:
    logging.error(f"❌ ERROR: Could not load configuration. Details: {e}")
    raise

# --- Initialize Observability ---
obs = Kansatsu(
    service_name="math-agent",
    service_version="1.0",
    dashboard_url="http://127.0.0.1:9000/update"
)

# --- 2. The Tools: Simple Math Functions ---
@obs.monitor()
def calculate_square_area(side: float) -> float:
    return side * side

@obs.monitor()
def calculate_rectangle_area(length: float, width: float) -> float:
    return length * width

@obs.monitor()
def calculate_circle_area(radius: float) -> float:
    import math
    return math.pi * (radius ** 2)

@obs.monitor()
def calculate_triangle_area(base: float, height: float) -> float:
    return 0.5 * base * height

# --- 3. Tool Schema ---
TOOL_SCHEMA = {
    "calculate_square_area": {"description": "Calculates the area of a square given the length of one side.", "function": calculate_square_area, "parameters": {"side": {"type": "number", "description": "The length of one side of the square."}}, "required": ["side"]},
    "calculate_rectangle_area": {"description": "Calculates the area of a rectangle given its length and width.", "function": calculate_rectangle_area, "parameters": {"length": {"type": "number", "description": "The length of the rectangle."}, "width": {"type": "number", "description": "The width of the rectangle."}}, "required": ["length", "width"]},
    "calculate_circle_area": {"description": "Calculates the area of a circle given its radius.", "function": calculate_circle_area, "parameters": {"radius": {"type": "number", "description": "The radius of the circle."}}, "required": ["radius"]},
    "calculate_triangle_area": {"description": "Calculates the area of a right-angled triangle given its base and height.", "function": calculate_triangle_area, "parameters": {"base": {"type": "number", "description": "The length of the base of the triangle."}, "height": {"type": "number", "description": "The height of the triangle."}}, "required": ["base", "height"]}
}

# --- 4. The Math Agent Class ---
class MathAgent:
    def __init__(self, llm: GenerativeModel, tools: Dict, observability: Kansatsu):
        self.llm = llm
        self.tools = tools
        self.obs = observability
        self.conversation_state = {}
        self.reset_state()

    def reset_state(self):
        self.conversation_state = {"current_tool": None, "collected_params": {}, "next_param_to_ask": None}

    # The decorator now handles token tracking automatically because the Gemini response
    # object has a `usage_metadata` attribute that the decorator knows how to parse.
    @obs.monitor(log_io=True, track_tokens=True)
    def _understand_and_extract(self, user_query: str) -> Optional[Dict]:
        """Uses the LLM to determine the user's intent and extract any available parameters."""
        prompt = f"""
        You are an expert at routing user requests to the correct tool.
        Analyze the user's query and determine which tool to use and what parameters have been provided.

        **Available Tools:**
        {json.dumps({k: {"description": v["description"], "parameters": v["parameters"]} for k, v in self.tools.items()}, indent=2)}

        **User Query:**
        "{user_query}"

        **Your Task:**
        Respond with a single JSON object containing:
        1. "tool_name": The name of the best-matching tool from the list. If no tool matches, use "unknown".
        2. "parameters": A JSON object containing any parameters you could extract from the user's query.
        """
        response_obj = self.llm.generate_content(prompt, generation_config={"response_mime_type": "application/json"})

        # The @obs.monitor decorator will automatically find and log the tokens from response_obj!
        # No manual logging is needed here.

        if response_obj and response_obj.text:
            try:
                return json.loads(response_obj.text)
            except json.JSONDecodeError:
                logging.error("Failed to decode JSON from intent classification.")
                return None
        return None

    @obs.monitor(log_io=True)
    def chat(self, user_input: str) -> str:
        """Main method to handle a turn in the conversation."""
        if self.conversation_state["next_param_to_ask"]:
            try:
                found_number = float(re.findall(r"[-+]?\d*\.\d+|\d+", user_input)[0])
                param_name = self.conversation_state["next_param_to_ask"]
                self.conversation_state["collected_params"][param_name] = found_number
                logging.info(f"Collected parameter '{param_name}' = {found_number}")
                self.conversation_state["next_param_to_ask"] = None
            except (ValueError, IndexError):
                return f"I'm sorry, I didn't understand that. Please provide a number for the {self.conversation_state['next_param_to_ask']}."

        if not self.conversation_state["current_tool"]:
            intent_data = self._understand_and_extract(user_input)
            if not intent_data or intent_data.get("tool_name") == "unknown":
                self.reset_state()
                return "I'm sorry, I can only help with calculating the area of a square, rectangle, circle, or triangle."
            tool_name = intent_data["tool_name"]
            self.conversation_state["current_tool"] = tool_name
            self.conversation_state["collected_params"] = intent_data.get("parameters", {})
            logging.info(f"Intent recognized. Tool: '{tool_name}', Initial params: {self.conversation_state['collected_params']}")

        tool_name = self.conversation_state["current_tool"]
        tool_info = self.tools[tool_name]
        required_params = tool_info["required"]
        collected_params = self.conversation_state["collected_params"]

        for param in required_params:
            if param not in collected_params:
                self.conversation_state["next_param_to_ask"] = param
                param_description = tool_info["parameters"][param]["description"]
                return f"I can help with that. What is {param_description.lower()}"

        logging.info(f"All parameters collected. Executing tool '{tool_name}'.")
        tool_function = tool_info["function"]
        try:
            result = tool_function(**collected_params)
            response = f"The area is {result:.2f}."
        except Exception as e:
            response = f"An error occurred during calculation: {e}"
        self.reset_state()
        return response

# --- 5. Main Execution Loop ---
if __name__ == "__main__":
    try:
        vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION)
        gemini_model = GenerativeModel(GEMINI_MODEL_NAME)
        agent = MathAgent(gemini_model, TOOL_SCHEMA, obs)
        logging.info("✅ Math Agent initialized successfully.")

        print("\n🤖 Math Agent is ready. Ask me to calculate an area!")
        print("   (e.g., 'area of a circle with radius 10', 'square side 4', or just 'rectangle')")
        print("   Type 'exit' or 'quit' to end.")

        while True:
            user_input = input("\n> Your Query: ")
            if user_input.lower() in ['exit', 'quit']:
                break

            tracer = obs.get_tracer()
            with tracer.start_as_current_span("user_interaction") as interaction_span:
                start_time = time.perf_counter()
                interaction_span.set_attribute("user.query", user_input)

                assistant_response = agent.chat(user_input)
                
                interaction_span.set_attribute("assistant.response", assistant_response)
                print(f"\n💡 AI Response: {assistant_response}")
                
                # Log end-to-end interaction time
                duration_ms = (time.perf_counter() - start_time) * 1000
                obs.log_interaction_time(duration_ms)

                # Ask for quality feedback
                quality_score_input = input("Rate response quality (1-5, or press Enter to skip): ")
                if quality_score_input.isdigit() and 1 <= int(quality_score_input) <= 5:
                    obs.log_quality_feedback(int(quality_score_input))
                    print("Thank you for your feedback!")

    finally:
        print("\nExiting application...")
        if 'obs' in locals():
            obs.shutdown()