FROM golang:1.24 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG GIT_SHA=unknown
RUN CGO_ENABLED=0 go build -trimpath \
    -ldflags "-s -w -X github.com/flotrpy/rootline/snapshotter/internal/server.BuildSHA=${GIT_SHA}" \
    -o /snapshotter ./cmd/snapshotter

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /snapshotter /snapshotter
EXPOSE 4318 8089
ENTRYPOINT ["/snapshotter", "-out", "/data/snapshots"]
