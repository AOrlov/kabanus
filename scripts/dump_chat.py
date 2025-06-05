import argparse
import asyncio
import json

from telethon import TelegramClient


async def dump_chat_history(api_id, api_hash, chat, output):
    async with TelegramClient('me', api_id, api_hash) as client:
        messages = client.iter_messages(chat, limit=None, reverse=True)
        counter = 0
        with open(output, 'w', encoding='utf-8') as f:
            async for msg in messages:
                if msg.message == "" or msg.message is None:
                    continue
                if counter % 1000 == 0:
                    print(f'Processed {counter} messages...')
                sender = await msg.get_sender()
                sender_name = sender.first_name or sender.username
                data = {
                        'sender': sender_name,
                        'text': msg.message,
                    }
                f.write(json.dumps(data, ensure_ascii=False) + '\n')
                counter += 1


def main():
    parser = argparse.ArgumentParser(description='Dump Telegram chat history to JSONL.')
    parser.add_argument('--api-id', required=True, help='Telegram API ID')
    parser.add_argument('--api-hash', required=True, help='Telegram API hash')
    parser.add_argument('--chat', required=True, help='Chat username or ID')
    parser.add_argument('--output', required=True, help='Output JSONL file')
    args = parser.parse_args()

    asyncio.run(dump_chat_history(args.api_id, args.api_hash, args.chat, args.output))


if __name__ == '__main__':
    main()
