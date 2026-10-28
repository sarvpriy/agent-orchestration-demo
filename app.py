import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

# Load environment variables from .env
load_dotenv()

# Read Groq configuration
api_key = os.getenv("GROQ_API_KEY")
model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Check API key
if not api_key:
    raise ValueError(
        "GROQ_API_KEY is missing. Add your actual Groq API key to the .env file."
    )

try:
    # Initialize Groq using LangChain
    llm = ChatGroq(
        api_key=api_key,
        model=model_name,
        temperature=0,
        max_retries=2,
    )

    # Test the connection
    print("Testing Groq connection...")
    response = llm.invoke(
        "Reply with exactly: Groq LangChain connection successful"
    )

    print("\nSUCCESS!")
    print(response.content)

except Exception as error:
    print("\nGroq connection failed.")
    print("Error type:", type(error).__name__)
    print("Details:", str(error))
    