# Kafka 配置
producer_conf = {
    'bootstrap.servers': '10.0.1.138:9092',
}

consumer_conf = {
    'bootstrap.servers': '10.0.1.138:9092',
    'group.id': 'my-group',  # 如果是要增加效率，要放在同一個組
    'auto.offset.reset': 'earliest'
}