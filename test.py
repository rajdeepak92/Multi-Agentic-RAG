import os 
import time 
import json 
import hashlib 
from typing import Dict, Any 
from langchain_openai import AzureChatOpenAI 
from langchain_core.prompts import ChatPromptTemplate 
from langchain_core.output_parsers import JsonOutputParser