from pyspark.sql import SparkSession
from pyspark.sql.window import Window
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType, BooleanType, TimestampType
from pyspark.sql.functions import from_json, col, window, sum as spark_sum, count as spark_count,avg, last, lit, to_timestamp, current_timestamp
from pyspark.sql import functions as SF

def main():
    schema = StructType([
        StructField("symbol", StringType(), True),
        StructField("type", StringType(), True),
        StructField("real_or_filled", StringType(), True),
        StructField("vwap_price_per_sec", DoubleType(), True),
        StructField("size_per_sec", IntegerType(), True),
        StructField("last_data_time", TimestampType(), True),
        StructField("start", TimestampType(), True),
        StructField("end", TimestampType(), True),
        StructField("current_time", TimestampType(), True),
        StructField("real_data_count", IntegerType(), True),
        StructField("filled_data_count", IntegerType(), True)
    ])

    spark = SparkSession.builder \
        .appName("spark_MA_data") \
        .master("local[2]") \
        .config("spark.executor.cores", "2") \
        .getOrCreate()
    
    kafka_df = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", "kafka:9092") \
        .option("subscribe", "kafka_per_sec_data_partition") \
        .option("startingOffsets", "earliest") \
        .option("maxOffsetsPerTrigger", "1000") \
        .option("failOnDataLoss", "false") \
        .load()
    

    def calculate_sma(df, window_duration, column_name):
        df_with_watermark = df.withWatermark("start", "15 seconds")

        sma_df = df_with_watermark.groupBy(
            SF.window(col("start"), f"{window_duration} seconds", "1 second"), col("symbol")
        ).agg(
            SF.sum(SF.when(col("size_per_sec") != 0, col("vwap_price_per_sec")).otherwise(0)).alias('sum_of_vwap'),
            SF.count(SF.when(col("size_per_sec") != 0, col("vwap_price_per_sec"))).alias('count_of_vwap'),  # !這邊不應該用otherwise...........
            SF.count("*").alias(f"{window_duration}_data_count"),
            SF.collect_list("start").alias("start_times"),
            SF.count(SF.when(col("real_or_filled") == "real", col("symbol"))).alias("real_data_count"),
            SF.count(SF.when(col("real_or_filled") != "real", col("symbol"))).alias("filled_data_count"),
        )
    
        window_spec = Window.partitionBy("symbol").orderBy("window.start")
        sma_df = sma_df.withColumn("rank", SF.row_number().over(window_spec)).orderBy("rank")


        sma_df = sma_df.withColumn(
            "initial_sma",
            SF.when(col('count_of_vwap') != 0, col('sum_of_vwap') / col('count_of_vwap')).otherwise(0)
        )
        sma_df = sma_df.withColumn(
            "prev_sma", SF.lag("initial_sma", 1).over(window_spec)
        )
        sma_df = sma_df.withColumn(
            column_name, 
            SF.when(col("initial_sma") == 0, SF.coalesce(col("prev_sma"), SF.lit(0)))
            .otherwise(col("initial_sma"))
        )
        sma_df = sma_df.select(            
            col("symbol"),
            lit("MA_data").alias("type"),
            lit(f"{window_duration}_MA_data").alias("MA_type"),
            col(f"window.start").alias("start"),
            col(f"window.end").alias("end"),
            col(column_name),
            col("sum_of_vwap"),
            col("count_of_vwap"),
            col(f"{window_duration}_data_count"),
            SF.current_timestamp().alias("current_time"),
            SF.element_at(col("start_times"), 1).alias("first_start_in_window"),
            SF.element_at(col("start_times"), -1).alias("last_start_in_window"),
            col("real_data_count"),
            col("filled_data_count"),
        )
        # 切記，會因為算式可能為空，導致輸出出錯，然後numInputRows就一直會是0


        # window_spec = Window.partitionBy("symbol").orderBy("start")
        # sma_df = sma_df.withColumn("rank", SF.row_number().over(window_spec)).orderBy("rank")
        return sma_df
    
    def send_to_kafka(df):
        df.selectExpr(
            "CAST(symbol AS STRING) AS key",
            "to_json(struct(*)) AS value"
        ).write \
            .format("kafka") \
            .option("kafka.bootstrap.servers", "kafka:9092") \
            .option("topic", "kafka_MA_data") \
            .save()
        
    def process_batch(df, epoch_id):
        try:
            df = df.selectExpr("CAST(value AS STRING) as json_data") \
                .select(from_json(col("json_data"), schema).alias("data")) \
                .select("data.*")
            sma_5 = calculate_sma(df, 5, "sma_5")
            sma_15 = calculate_sma(df, 15, "sma_15")
            sma_30 = calculate_sma(df, 30, "sma_30")

            send_to_kafka(sma_5)
            send_to_kafka(sma_15)
            send_to_kafka(sma_30)
            
            # sma_5.selectExpr(
            #     "CAST(symbol AS STRING) AS key",
            #     "to_json(struct(*)) AS value"
            # ).write \
            #     .format("kafka") \
            #     .option("kafka.bootstrap.servers", "kafka:9092") \
            #     .option("topic", "kafka_MA_data") \
            #     .save()
            
        except Exception as e:
            print(f"Error processing batch {epoch_id}: {e}")
            
    query = kafka_df.writeStream \
        .foreachBatch(process_batch) \
        .option("checkpointLocation", "/app/tmp/spark_checkpoints/spark_ma") \
        .start()
    query.awaitTermination()

if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------------------------------
            # df = df.selectExpr("CAST(value AS STRING) as json_data") \
            #     .select(from_json(col("json_data"), schema).alias("data")) \
            #     .select("data.*")
            
            # sma_5 = calculate_sma(df, 5, "sma_5").withColumnRenamed("window.start", "start_5").withColumnRenamed("window.end", "end_5")
            # sma_10 = calculate_sma(df, 10, "sma_10").withColumnRenamed("window.start", "start_10").withColumnRenamed("window.end", "end_10")
            # sma_30 = calculate_sma(df, 30, "sma_30").withColumnRenamed("window.start", "start_30").withColumnRenamed("window.end", "end_30")

            # final_df = sma_5.join(sma_10, ["symbol", "start_5", "end_5"]) \
            #                 .join(sma_30, ["symbol", "start_5", "end_5"]) \
            #                 .select(
            #                     "symbol",
            #                     "start_5", "end_5", "sma_5", "5_data_count",
            #                     "start_10", "end_10", "sma_10", "10_data_count",
            #                     "start_30", "end_30", "sma_30", "30_data_count"
            #                 )
            # final_df.selectExpr(
            #     "CAST(symbol AS STRING) AS key",
            #     "to_json(struct(*)) AS value"
            # ).write \
            #     .format("kafka") \
            #     .option("kafka.bootstrap.servers", "kafka:9092") \
            #     .option("topic", "kafka_MA_data") \
            #     .save()