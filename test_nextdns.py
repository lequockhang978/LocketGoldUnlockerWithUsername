import asyncio
import aiohttp
from app.config import NEXTDNS_KEY

async def test():
    headers = {
        "X-Api-Key": NEXTDNS_KEY,
        "Content-Type": "application/json"
    }
    print(f"Testing NextDNS API Key: {NEXTDNS_KEY[:10]}...")
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get("https://api.nextdns.io/profiles") as res:
            print(f"Status: {res.status}")
            data = await res.json()
            if res.status == 200:
                profiles = data.get('data', [])
                print(f"OK! Found {len(profiles)} profiles")
                for p in profiles[:5]:
                    print(f"  - {p.get('name')} ({p.get('id')})")
            else:
                print(f"FAILED: {data}")

asyncio.run(test())
