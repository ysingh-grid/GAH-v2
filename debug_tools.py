"""
Debug: Check if tools are loading correctly
"""

print("Step 1: Importing registry...")
try:
    from tools.tools_registry import registry
    print("✅ Registry imported")
except Exception as e:
    print(f"❌ Failed to import registry: {e}")
    exit(1)

print("\nStep 2: Getting all tools...")
try:
    all_tools = registry.get_all()
    print(f"✅ Got {len(all_tools)} tools")
    print(f"   Tools: {[t.__name__ for t in all_tools]}")
except Exception as e:
    print(f"❌ Failed to get tools: {e}")
    exit(1)

print("\nStep 3: Listing tool details...")
try:
    tools_info = registry.list_tools()
    for name, doc in tools_info.items():
        print(f"   - {name}: {doc}")
except Exception as e:
    print(f"❌ Failed to list tools: {e}")
    exit(1)

print("\n✅ All tools loaded successfully!")