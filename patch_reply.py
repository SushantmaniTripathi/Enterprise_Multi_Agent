with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the fallback block using unique anchor text
OLD_ANCHOR = '# Fallback: if no match found in DB, return contact message'
NEW_BLOCK = '''# Step 2: Extractive failed - let the LLM synthesize from context
    if reply == "__NO_MATCH__":
        persona = get_persona_prompt(bot_key)
        llm_prompt = (
            persona + "\\n\\nContext:\\n" + ctx +
            "\\n\\nUser: " + message +
            "\\n\\nHIERARCHY: Official Docs > Admin Messages > Community."
            "\\nCRITICAL INSTRUCTION 1: Answer ONLY from the Context. If truly no answer, say 'idk tbh'."
            "\\nCRITICAL INSTRUCTION 2: Do NOT say 'contact @sam_support007' unless you have zero info."
            "\\nCRITICAL INSTRUCTION 3: Sound like a human texting. Lowercase, imperfect."
        )
        reply = ask_llm(llm_prompt).strip()
    elif is_outdated and str(data_year) not in reply and any(k in message.lower() for k in ["latest", "recent", "new", "today"]):
        reply += " (check pinned messages for latest info)"'''

if OLD_ANCHOR not in content:
    print("ERROR: anchor not found in file!")
else:
    # Find the full block to replace (from anchor to end of the elif)
    start = content.index(OLD_ANCHOR)
    # Find the end of the whole if/elif block (the blank line before "return reply, ctx")
    end = content.index('\n    \n    return reply, ctx', start)
    content = content[:start] + NEW_BLOCK + content[end:]
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("PATCHED OK")
