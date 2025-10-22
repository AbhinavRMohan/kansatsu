# FILE: examples/physio_assistant.py

import os
import json
import logging
import re
import time
from typing import Dict, Any, Optional

# Our observability module
from kansatsu import Kansatsu

from openai import OpenAI
from opentelemetry import trace

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    MODEL_NAME = "gpt-4o-mini" 
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OpenAI API key not found in environment. Please set OPENAI_API_KEY.")
    logging.info("✅ Configuration loaded and OpenAI API key found.")
except Exception as e:
    logging.error(f"❌ ERROR: Could not load configuration. Details: {e}")
    raise

# --- Initialize Observability ---
obs = Kansatsu(
    service_name="physiology-agent",
    service_version="1.0",
    dashboard_url="http://127.0.0.1:9999/update",
)

@obs.monitor()
def calculate_total_blood_oxygen(CHgb: float, SaO2: float, PaO2: float) -> float:
    return (1.34*CHgb*SaO2) + (0.003*PaO2)

@obs.monitor()
def calculate_shunt(CaO2: float, CvO2: float, CcO2: float) -> float:
    return (CcO2 - CaO2)/(CcO2 - CvO2)

TOOL_SCHEMA = {
    "calculate_shunt": {
        "description": "Calculates shunt.", 
        "function": calculate_shunt, 
        "parameters": {
            "CcO2": {
                "type": "number", "description": "The capillary O2 concentration."
            },
            "CaO2": {
                "type": "number", "description": "The arterial O2 concentration."
            },
            "CvO2": {
                "type": "number", "description": "The venous O2 concentration."
            }
        }, 
        "required": ["CcO2", "CaO2", "CvO2"]
    },
    "calculate_total_blood_oxygen": {
        "description": "Calculates the total blood oxygen given the appropriate parameters.", 
        "function": calculate_total_blood_oxygen, 
        "parameters": {
            "CHgb": {
                "type": "number", "description": "The concentration of hemoglobin"
            },
            "SaO2": {
                "type": "number", "description": "The saturation of oxygen"
            },
            "PaO2": {
                "type": "number", "description": "The partial pressure of oxygen"
            }
        },
        "required": ["CHgb", "SaO2", "PaO2"]
    }
}

class PhisAgent:
    def __init__(self, client: OpenAI, model_name: str, tools: Dict, observability: Kansatsu):
        self.client = client
        self.model_name = model_name
        self.tools = tools
        self.obs = observability
        self.obs_last_call = {}  
        self.reset_state()

    def reset_state(self):
        self.conversation_state = {
            "current_tool": None,
            "collected_params": {},
            "next_param_to_ask": None
        }

    @obs.monitor(log_io=True, track_tokens=True)
    def _understand_and_extract(self, user_query: str) -> Dict[str, Any]:
        """Use LLM to determine intent and extract parameters."""

        span = trace.get_current_span()
        
        tools_info = {k: {"description": v["description"], "parameters": v["parameters"]} for k, v in self.tools.items()}
        prompt = f"""
        You are an expert at routing user requests to the correct tool.
        Analyze the user's query and determine which tool to use and what parameters have been provided.
        
        Available Tools:
        {json.dumps(tools_info, indent=2)}
        
        User Query: "{user_query}"
        
        Respond with a JSON object:
        {{
            "tool_name": "<best matching tool or 'unknown'>",
            "parameters": {{ ... extracted numeric parameters ... }}
        }}
        """

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "You are a JSON-only reasoning agent."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        completion_text = response.choices[0].message.content

        # --- Token usage for dashboard ---
        prompt_tokens = getattr(response.usage, "prompt_tokens", 0)
        completion_tokens = getattr(response.usage, "completion_tokens", 0)
        total_tokens = getattr(response.usage, "total_tokens", prompt_tokens + completion_tokens)

        if total_tokens > 0:
            self.obs.log_method_llm_usage("_understand_and_extract", prompt_tokens, completion_tokens, total_tokens)

        try:
            parsed_json = json.loads(completion_text)
        except Exception as e:
            logging.error(f"Failed to parse JSON response: {e}")
            parsed_json = {}

        span.add_event(
            "llm_thought_process",
            {
                "llm.prompt": prompt,
                "llm.completion.raw": completion_text,
                "llm.completion.parsed": json.dumps(parsed_json, default=str)
            }
        )

        self.obs_last_call.update({
            "prompt": prompt,
            "completion": completion_text,
            "total_tokens": total_tokens
        })

        return {"_kansatsu": self.obs_last_call, "parsed": parsed_json}

    @obs.monitor(log_io=True, track_tokens=True)
    def chat(self, user_input: str) -> str:
        state = self.conversation_state

        # If waiting for a parameter input
        if state["next_param_to_ask"]:
            try:
                value = float(re.findall(r"[-+]?\d*\.\d+|\d+", user_input)[0])
                param_name = state["next_param_to_ask"]
                state["collected_params"][param_name] = value
                logging.info(f"Collected parameter '{param_name}' = {value}")
                state["next_param_to_ask"] = None
            except (ValueError, IndexError):
                return f"Please provide a numeric value for {state['next_param_to_ask']}."

        # If no tool selected, determine intent
        if not state["current_tool"]:
            result = self._understand_and_extract(user_input)
            intent_data = result.get("parsed", {})
            if not intent_data or intent_data.get("tool_name") == "unknown":
                self.reset_state()
                return "I can only help with blood oxygen content or shunt calculations."
            state["current_tool"] = intent_data["tool_name"]
            state["collected_params"] = intent_data.get("parameters", {})
            logging.info(f"Intent recognized: {state['current_tool']} with initial params {state['collected_params']}")

        tool_name = state["current_tool"]
        tool_info = self.tools[tool_name]
        required_params = tool_info["required"]

        # Ask for missing parameters
        for param in required_params:
            if param not in state["collected_params"]:
                state["next_param_to_ask"] = param
                desc = tool_info["parameters"][param]["description"]
                return f"I can help with that. What is {desc.lower()}?"

        # Execute tool if all parameters collected
        logging.info(f"Executing tool '{tool_name}' with params {state['collected_params']}")
        try:
            result = tool_info["function"](**state["collected_params"])
            response = f"The result is {result:.2f}."
        except Exception as e:
            response = f"Error during calculation: {e}"

        # Update last call observability
        self.obs_last_call.update({
            "tool_name": tool_name,
            "collected_params": state["collected_params"],
            "tool_result": result if 'result' in locals() else None
        })

        self.reset_state()
        return response

if __name__ == "__main__":
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        agent = PhisAgent(client, MODEL_NAME, TOOL_SCHEMA, obs)
        logging.info("Physiology Assistant initialized successfully.")

        print("\nHere is what all I can do!")
        print("1.  Whole blood oxygen content:\n   *   CaO2 (ml/100ml)\n   *   [Hgb] (g/100ml)\n   *   SaO2 (decimal)\n   *   PaO2 (mmHg)")
        print("2.  Shunt\n   *   CcO2 (Capillary Conc.)\n   *   CaO2 (Arterial Conc.)\n   *   CvO2 (Venous Conc.)")
        print("   Type 'exit' or 'quit' to end.")

        while True:
            user_input = input("\n> Your Query: ")
            if user_input.lower() in ['exit', 'quit']:
                break

            tracer = obs.get_tracer()
            with tracer.start_as_current_span("user_interaction") as interaction_span:
                start_time = time.perf_counter()
                interaction_span.set_attribute("user.query", user_input)
                obs.check_responsible_ai(user_input, interaction_span)
                assistant_response = agent.chat(user_input)
                obs.check_responsible_ai(assistant_response, interaction_span)
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