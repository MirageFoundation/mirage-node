#!/usr/bin/env python3
"""
Check gRPC connectivity to a Mirage node.

Usage:
    conda run -n mirage-node python3 scripts/check_grpc.py [host:port]

Default host:port is 127.0.0.1:9090
"""
import sys
import grpc

def check_grpc(address: str) -> bool:
    """Test gRPC connectivity by querying node info."""
    try:
        from cosmos.base.tendermint.v1beta1 import query_pb2, query_pb2_grpc
    except ImportError:
        print("ERROR: cosmos-sdk protobuf stubs not found.")
        print("This script requires the cosmos protobuf definitions.")
        print("Falling back to raw gRPC channel check...")
        return check_grpc_raw(address)

    channel = grpc.insecure_channel(address)
    try:
        stub = query_pb2_grpc.ServiceStub(channel)
        request = query_pb2.GetNodeInfoRequest()
        response = stub.GetNodeInfo(request, timeout=10)
        print(f"OK: gRPC is working on {address}")
        print(f"    Network: {response.default_node_info.network}")
        print(f"    Moniker: {response.default_node_info.moniker}")
        print(f"    Version: {response.application_version.version}")
        return True
    except grpc.RpcError as e:
        print(f"FAIL: gRPC error on {address}: {e.code()} - {e.details()}")
        return False
    except Exception as e:
        print(f"FAIL: {e}")
        return False
    finally:
        channel.close()


def check_grpc_raw(address: str) -> bool:
    """Raw gRPC channel connectivity check without protobuf stubs."""
    channel = grpc.insecure_channel(address)
    try:
        grpc.channel_ready_future(channel).result(timeout=5)
        print(f"OK: gRPC channel is reachable on {address}")
        print("    (Full query test skipped - protobuf stubs not available)")
        return True
    except grpc.FutureTimeoutError:
        print(f"FAIL: gRPC channel timeout on {address}")
        return False
    except Exception as e:
        print(f"FAIL: {e}")
        return False
    finally:
        channel.close()


def main():
    address = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:9090"
    print(f"Checking gRPC on {address}...")
    success = check_grpc_raw(address)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

