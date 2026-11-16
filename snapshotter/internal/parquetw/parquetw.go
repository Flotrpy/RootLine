// Package parquetw writes snapshot rows to zstd-compressed Parquet files
// with the schemas from the data contract.
package parquetw

import (
	"fmt"
	"os"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/compress"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"

	"github.com/flotrpy/rootline/snapshotter/internal/rows"
)

// Schemas, in contract column order.
var (
	SpanSchema = arrow.NewSchema([]arrow.Field{
		{Name: "trace_id", Type: arrow.BinaryTypes.String},
		{Name: "span_id", Type: arrow.BinaryTypes.String},
		{Name: "parent_span_id", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "service", Type: arrow.BinaryTypes.String},
		{Name: "operation", Type: arrow.BinaryTypes.String},
		{Name: "start_unix_nano", Type: arrow.PrimitiveTypes.Int64},
		{Name: "duration_ns", Type: arrow.PrimitiveTypes.Int64},
		{Name: "status_code", Type: arrow.BinaryTypes.String},
		{Name: "attributes", Type: arrow.BinaryTypes.String},
	}, nil)
	MetricSchema = arrow.NewSchema([]arrow.Field{
		{Name: "ts", Type: arrow.PrimitiveTypes.Int64},
		{Name: "service", Type: arrow.BinaryTypes.String},
		{Name: "metric_name", Type: arrow.BinaryTypes.String},
		{Name: "value", Type: arrow.PrimitiveTypes.Float64},
		{Name: "labels", Type: arrow.BinaryTypes.String},
	}, nil)
	LogSchema = arrow.NewSchema([]arrow.Field{
		{Name: "ts", Type: arrow.PrimitiveTypes.Int64},
		{Name: "service", Type: arrow.BinaryTypes.String},
		{Name: "severity", Type: arrow.BinaryTypes.String},
		{Name: "body", Type: arrow.BinaryTypes.String},
		{Name: "trace_id", Type: arrow.BinaryTypes.String, Nullable: true},
	}, nil)
)

func appendOpt(b *array.StringBuilder, s *string) {
	if s == nil {
		b.AppendNull()
		return
	}
	b.Append(*s)
}

func write(path string, rec arrow.RecordBatch) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	props := parquet.NewWriterProperties(parquet.WithCompression(compress.Codecs.Zstd))
	tbl := array.NewTableFromRecords(rec.Schema(), []arrow.RecordBatch{rec})
	defer tbl.Release()
	if err := pqarrow.WriteTable(tbl, f, 64*1024, props, pqarrow.DefaultWriterProps()); err != nil {
		_ = f.Close()
		return fmt.Errorf("write %s: %w", path, err)
	}
	// WriteTable closes the file through the parquet writer.
	return nil
}

// WriteSpans writes spans.parquet.
func WriteSpans(path string, s []rows.Span) error {
	b := array.NewRecordBuilder(memory.DefaultAllocator, SpanSchema)
	defer b.Release()
	for _, x := range s {
		b.Field(0).(*array.StringBuilder).Append(x.TraceID)
		b.Field(1).(*array.StringBuilder).Append(x.SpanID)
		appendOpt(b.Field(2).(*array.StringBuilder), x.ParentSpanID)
		b.Field(3).(*array.StringBuilder).Append(x.Service)
		b.Field(4).(*array.StringBuilder).Append(x.Operation)
		b.Field(5).(*array.Int64Builder).Append(x.StartUnixNano)
		b.Field(6).(*array.Int64Builder).Append(x.DurationNs)
		b.Field(7).(*array.StringBuilder).Append(x.StatusCode)
		b.Field(8).(*array.StringBuilder).Append(x.Attributes)
	}
	rec := b.NewRecordBatch()
	defer rec.Release()
	return write(path, rec)
}

// WriteMetrics writes metrics.parquet.
func WriteMetrics(path string, m []rows.Metric) error {
	b := array.NewRecordBuilder(memory.DefaultAllocator, MetricSchema)
	defer b.Release()
	for _, x := range m {
		b.Field(0).(*array.Int64Builder).Append(x.Ts)
		b.Field(1).(*array.StringBuilder).Append(x.Service)
		b.Field(2).(*array.StringBuilder).Append(x.MetricName)
		b.Field(3).(*array.Float64Builder).Append(x.Value)
		b.Field(4).(*array.StringBuilder).Append(x.Labels)
	}
	rec := b.NewRecordBatch()
	defer rec.Release()
	return write(path, rec)
}

// WriteLogs writes logs.parquet.
func WriteLogs(path string, l []rows.Log) error {
	b := array.NewRecordBuilder(memory.DefaultAllocator, LogSchema)
	defer b.Release()
	for _, x := range l {
		b.Field(0).(*array.Int64Builder).Append(x.Ts)
		b.Field(1).(*array.StringBuilder).Append(x.Service)
		b.Field(2).(*array.StringBuilder).Append(x.Severity)
		b.Field(3).(*array.StringBuilder).Append(x.Body)
		appendOpt(b.Field(4).(*array.StringBuilder), x.TraceID)
	}
	rec := b.NewRecordBatch()
	defer rec.Release()
	return write(path, rec)
}
