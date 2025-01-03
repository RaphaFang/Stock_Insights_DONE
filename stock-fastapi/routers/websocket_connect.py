from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import asyncio
# from kafka import KafkaConsumer
from aiokafka import AIOKafkaConsumer
import json

router = APIRouter()
per_sec_queue = asyncio.Queue()
MA_queue = asyncio.Queue()

headers = {"Content-Type": "application/json; charset=utf-8"}

# !這邊應該要修正，因為好像會不斷重新建立 consumer
async def per_sec_consumer_loop(topic_name):
    # 用一般的KafkaConsumer會導致組塞
    consumer = AIOKafkaConsumer(
        topic_name,
        bootstrap_servers='10.0.1.138:9092',
        group_id='ws_per_sec_group',
        auto_offset_reset='earliest',
        # loop=asyncio.get_event_loop()  # 新版本不用這個了
    )
    await consumer.start()
    try:
        async for message in consumer:
            await per_sec_queue.put(message.value.decode('utf-8'))
    finally:
        await consumer.stop()
# !這邊應該要修正，因為好像會不斷重新建立 consumer

async def MA_consumer_loop(topic_name):
    consumer = AIOKafkaConsumer(
        topic_name,
        bootstrap_servers='10.0.1.138:9092',
        group_id='ws_MA_group',
        auto_offset_reset='earliest',
    )
    await consumer.start()
    try:
        async for message in consumer:
            await MA_queue.put(message.value.decode("utf-8"))
    finally:
        await consumer.stop()


@router.websocket("/ws/data")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            try:
                per_sec_data = await per_sec_queue.get()
                MA_data = await MA_queue.get()
                if per_sec_data:
                    await ws.send_text(per_sec_data)
                if MA_data:
                    await ws.send_text(MA_data)
            except WebSocketDisconnect:
                print("WebSocket disconnected")
                break
    except Exception as e:
        print(f"WebSocket connection error: {e}")
        await ws.close()
    finally:
        await ws.close()

# ! 接下來考慮，lkafka這邊先多一個分區，接著我框架在多一個分區，就可以讓接收端更快