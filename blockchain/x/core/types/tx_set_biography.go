package types

import (
	"fmt"
	"io"

	"github.com/cosmos/gogoproto/proto"
)

// MsgSetBiography sets a biography for an address (subscriber-only feature).
type MsgSetBiography struct {
	Authority          string `protobuf:"bytes,1,opt,name=authority,proto3" json:"authority,omitempty"`
	EnvelopePubkey     []byte `protobuf:"bytes,2,opt,name=envelope_pubkey,json=envelopePubkey,proto3" json:"envelope_pubkey,omitempty"`
	EnvelopeBlockHash  []byte `protobuf:"bytes,3,opt,name=envelope_block_hash,json=envelopeBlockHash,proto3" json:"envelope_block_hash,omitempty"`
	EnvelopeDifficulty uint64 `protobuf:"varint,4,opt,name=envelope_difficulty,json=envelopeDifficulty,proto3" json:"envelope_difficulty,omitempty"`
	EnvelopePow        uint64 `protobuf:"varint,5,opt,name=envelope_pow,json=envelopePow,proto3" json:"envelope_pow,omitempty"`
	EnvelopeTimestamp  uint64 `protobuf:"varint,6,opt,name=envelope_timestamp,json=envelopeTimestamp,proto3" json:"envelope_timestamp,omitempty"`
	EnvelopeSignature  []byte `protobuf:"bytes,10,opt,name=envelope_signature,json=envelopeSignature,proto3" json:"envelope_signature,omitempty"`
	Target             string `protobuf:"bytes,100,opt,name=target,proto3" json:"target,omitempty"`
	Biography          string `protobuf:"bytes,101,opt,name=biography,proto3" json:"biography,omitempty"`
}

func (m *MsgSetBiography) Reset()         { *m = MsgSetBiography{} }
func (m *MsgSetBiography) String() string { return proto.CompactTextString(m) }
func (*MsgSetBiography) ProtoMessage()    {}
func (*MsgSetBiography) XXX_MessageName() string {
	return "mirage.core.v1.MsgSetBiography"
}

func (m *MsgSetBiography) GetAuthority() string {
	if m != nil {
		return m.Authority
	}
	return ""
}
func (m *MsgSetBiography) GetEnvelopePubkey() []byte {
	if m != nil {
		return m.EnvelopePubkey
	}
	return nil
}
func (m *MsgSetBiography) GetEnvelopeBlockHash() []byte {
	if m != nil {
		return m.EnvelopeBlockHash
	}
	return nil
}
func (m *MsgSetBiography) GetEnvelopeDifficulty() uint64 {
	if m != nil {
		return m.EnvelopeDifficulty
	}
	return 0
}
func (m *MsgSetBiography) GetEnvelopePow() uint64 {
	if m != nil {
		return m.EnvelopePow
	}
	return 0
}
func (m *MsgSetBiography) GetEnvelopeTimestamp() uint64 {
	if m != nil {
		return m.EnvelopeTimestamp
	}
	return 0
}
func (m *MsgSetBiography) GetEnvelopeSignature() []byte {
	if m != nil {
		return m.EnvelopeSignature
	}
	return nil
}
func (m *MsgSetBiography) GetTarget() string {
	if m != nil {
		return m.Target
	}
	return ""
}
func (m *MsgSetBiography) GetBiography() string {
	if m != nil {
		return m.Biography
	}
	return ""
}

func (m *MsgSetBiography) Marshal() (dAtA []byte, err error) {
	size := m.Size()
	dAtA = make([]byte, size)
	n, err := m.MarshalToSizedBuffer(dAtA[:size])
	if err != nil {
		return nil, err
	}
	return dAtA[:n], nil
}

func (m *MsgSetBiography) MarshalTo(dAtA []byte) (int, error) {
	size := m.Size()
	return m.MarshalToSizedBuffer(dAtA[:size])
}

func (m *MsgSetBiography) MarshalToSizedBuffer(dAtA []byte) (int, error) {
	i := len(dAtA)
	_ = i
	var l int
	_ = l
	if len(m.Biography) > 0 {
		i -= len(m.Biography)
		copy(dAtA[i:], m.Biography)
		i = encodeVarintTx(dAtA, i, uint64(len(m.Biography)))
		i--
		dAtA[i] = 0x6
		i--
		dAtA[i] = 0xaa
	}
	if len(m.Target) > 0 {
		i -= len(m.Target)
		copy(dAtA[i:], m.Target)
		i = encodeVarintTx(dAtA, i, uint64(len(m.Target)))
		i--
		dAtA[i] = 0x6
		i--
		dAtA[i] = 0xa2
	}
	if len(m.EnvelopeSignature) > 0 {
		i -= len(m.EnvelopeSignature)
		copy(dAtA[i:], m.EnvelopeSignature)
		i = encodeVarintTx(dAtA, i, uint64(len(m.EnvelopeSignature)))
		i--
		dAtA[i] = 0x52
	}
	if m.EnvelopeTimestamp != 0 {
		i = encodeVarintTx(dAtA, i, uint64(m.EnvelopeTimestamp))
		i--
		dAtA[i] = 0x30
	}
	if m.EnvelopePow != 0 {
		i = encodeVarintTx(dAtA, i, uint64(m.EnvelopePow))
		i--
		dAtA[i] = 0x28
	}
	if m.EnvelopeDifficulty != 0 {
		i = encodeVarintTx(dAtA, i, uint64(m.EnvelopeDifficulty))
		i--
		dAtA[i] = 0x20
	}
	if len(m.EnvelopeBlockHash) > 0 {
		i -= len(m.EnvelopeBlockHash)
		copy(dAtA[i:], m.EnvelopeBlockHash)
		i = encodeVarintTx(dAtA, i, uint64(len(m.EnvelopeBlockHash)))
		i--
		dAtA[i] = 0x1a
	}
	if len(m.EnvelopePubkey) > 0 {
		i -= len(m.EnvelopePubkey)
		copy(dAtA[i:], m.EnvelopePubkey)
		i = encodeVarintTx(dAtA, i, uint64(len(m.EnvelopePubkey)))
		i--
		dAtA[i] = 0x12
	}
	if len(m.Authority) > 0 {
		i -= len(m.Authority)
		copy(dAtA[i:], m.Authority)
		i = encodeVarintTx(dAtA, i, uint64(len(m.Authority)))
		i--
		dAtA[i] = 0xa
	}
	return len(dAtA) - i, nil
}

func (m *MsgSetBiography) Size() (n int) {
	if m == nil {
		return 0
	}
	var l int
	_ = l
	l = len(m.Authority)
	if l > 0 {
		n += 1 + l + sovTx(uint64(l))
	}
	l = len(m.EnvelopePubkey)
	if l > 0 {
		n += 1 + l + sovTx(uint64(l))
	}
	l = len(m.EnvelopeBlockHash)
	if l > 0 {
		n += 1 + l + sovTx(uint64(l))
	}
	if m.EnvelopeDifficulty != 0 {
		n += 1 + sovTx(uint64(m.EnvelopeDifficulty))
	}
	if m.EnvelopePow != 0 {
		n += 1 + sovTx(uint64(m.EnvelopePow))
	}
	if m.EnvelopeTimestamp != 0 {
		n += 1 + sovTx(uint64(m.EnvelopeTimestamp))
	}
	l = len(m.EnvelopeSignature)
	if l > 0 {
		n += 1 + l + sovTx(uint64(l))
	}
	l = len(m.Target)
	if l > 0 {
		n += 2 + l + sovTx(uint64(l))
	}
	l = len(m.Biography)
	if l > 0 {
		n += 2 + l + sovTx(uint64(l))
	}
	return n
}

func (m *MsgSetBiography) Unmarshal(dAtA []byte) error {
	l := len(dAtA)
	iNdEx := 0
	for iNdEx < l {
		preIndex := iNdEx
		var wire uint64
		for shift := uint(0); ; shift += 7 {
			if shift >= 64 {
				return ErrIntOverflowTx
			}
			if iNdEx >= l {
				return io.ErrUnexpectedEOF
			}
			b := dAtA[iNdEx]
			iNdEx++
			wire |= uint64(b&0x7F) << shift
			if b < 0x80 {
				break
			}
		}
		fieldNum := int32(wire >> 3)
		wireType := int(wire & 0x7)
		if wireType == 4 {
			return fmt.Errorf("proto: MsgSetBiography: wiretype end group for non-group")
		}
		if fieldNum <= 0 {
			return fmt.Errorf("proto: MsgSetBiography: illegal tag %d (wire type %d)", fieldNum, wire)
		}
		switch fieldNum {
		case 1:
			if wireType != 2 {
				return fmt.Errorf("proto: wrong wireType = %d for field Authority", wireType)
			}
			var stringLen uint64
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				stringLen |= uint64(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
			intStringLen := int(stringLen)
			if intStringLen < 0 {
				return ErrInvalidLengthTx
			}
			postIndex := iNdEx + intStringLen
			if postIndex < 0 {
				return ErrInvalidLengthTx
			}
			if postIndex > l {
				return io.ErrUnexpectedEOF
			}
			m.Authority = string(dAtA[iNdEx:postIndex])
			iNdEx = postIndex
		case 2:
			if wireType != 2 {
				return fmt.Errorf("proto: wrong wireType = %d for field EnvelopePubkey", wireType)
			}
			var byteLen int
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				byteLen |= int(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
			if byteLen < 0 {
				return ErrInvalidLengthTx
			}
			postIndex := iNdEx + byteLen
			if postIndex < 0 {
				return ErrInvalidLengthTx
			}
			if postIndex > l {
				return io.ErrUnexpectedEOF
			}
			m.EnvelopePubkey = append(m.EnvelopePubkey[:0], dAtA[iNdEx:postIndex]...)
			if m.EnvelopePubkey == nil {
				m.EnvelopePubkey = []byte{}
			}
			iNdEx = postIndex
		case 3:
			if wireType != 2 {
				return fmt.Errorf("proto: wrong wireType = %d for field EnvelopeBlockHash", wireType)
			}
			var byteLen int
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				byteLen |= int(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
			if byteLen < 0 {
				return ErrInvalidLengthTx
			}
			postIndex := iNdEx + byteLen
			if postIndex < 0 {
				return ErrInvalidLengthTx
			}
			if postIndex > l {
				return io.ErrUnexpectedEOF
			}
			m.EnvelopeBlockHash = append(m.EnvelopeBlockHash[:0], dAtA[iNdEx:postIndex]...)
			if m.EnvelopeBlockHash == nil {
				m.EnvelopeBlockHash = []byte{}
			}
			iNdEx = postIndex
		case 4:
			if wireType != 0 {
				return fmt.Errorf("proto: wrong wireType = %d for field EnvelopeDifficulty", wireType)
			}
			m.EnvelopeDifficulty = 0
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				m.EnvelopeDifficulty |= uint64(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
		case 5:
			if wireType != 0 {
				return fmt.Errorf("proto: wrong wireType = %d for field EnvelopePow", wireType)
			}
			m.EnvelopePow = 0
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				m.EnvelopePow |= uint64(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
		case 6:
			if wireType != 0 {
				return fmt.Errorf("proto: wrong wireType = %d for field EnvelopeTimestamp", wireType)
			}
			m.EnvelopeTimestamp = 0
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				m.EnvelopeTimestamp |= uint64(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
		case 10:
			if wireType != 2 {
				return fmt.Errorf("proto: wrong wireType = %d for field EnvelopeSignature", wireType)
			}
			var byteLen int
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				byteLen |= int(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
			if byteLen < 0 {
				return ErrInvalidLengthTx
			}
			postIndex := iNdEx + byteLen
			if postIndex < 0 {
				return ErrInvalidLengthTx
			}
			if postIndex > l {
				return io.ErrUnexpectedEOF
			}
			m.EnvelopeSignature = append(m.EnvelopeSignature[:0], dAtA[iNdEx:postIndex]...)
			if m.EnvelopeSignature == nil {
				m.EnvelopeSignature = []byte{}
			}
			iNdEx = postIndex
		case 100:
			if wireType != 2 {
				return fmt.Errorf("proto: wrong wireType = %d for field Target", wireType)
			}
			var stringLen uint64
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				stringLen |= uint64(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
			intStringLen := int(stringLen)
			if intStringLen < 0 {
				return ErrInvalidLengthTx
			}
			postIndex := iNdEx + intStringLen
			if postIndex < 0 {
				return ErrInvalidLengthTx
			}
			if postIndex > l {
				return io.ErrUnexpectedEOF
			}
			m.Target = string(dAtA[iNdEx:postIndex])
			iNdEx = postIndex
		case 101:
			if wireType != 2 {
				return fmt.Errorf("proto: wrong wireType = %d for field Biography", wireType)
			}
			var stringLen uint64
			for shift := uint(0); ; shift += 7 {
				if shift >= 64 {
					return ErrIntOverflowTx
				}
				if iNdEx >= l {
					return io.ErrUnexpectedEOF
				}
				b := dAtA[iNdEx]
				iNdEx++
				stringLen |= uint64(b&0x7F) << shift
				if b < 0x80 {
					break
				}
			}
			intStringLen := int(stringLen)
			if intStringLen < 0 {
				return ErrInvalidLengthTx
			}
			postIndex := iNdEx + intStringLen
			if postIndex < 0 {
				return ErrInvalidLengthTx
			}
			if postIndex > l {
				return io.ErrUnexpectedEOF
			}
			m.Biography = string(dAtA[iNdEx:postIndex])
			iNdEx = postIndex
		default:
			iNdEx = preIndex
			skippy, err := skipTx(dAtA[iNdEx:])
			if err != nil {
				return err
			}
			if (skippy < 0) || (iNdEx+skippy) < 0 {
				return ErrInvalidLengthTx
			}
			if iNdEx+skippy > l {
				return io.ErrUnexpectedEOF
			}
			iNdEx += skippy
		}
	}
	if iNdEx > l {
		return io.ErrUnexpectedEOF
	}
	return nil
}

type MsgSetBiographyResponse struct{}

func (m *MsgSetBiographyResponse) Reset()         { *m = MsgSetBiographyResponse{} }
func (m *MsgSetBiographyResponse) String() string { return proto.CompactTextString(m) }
func (*MsgSetBiographyResponse) ProtoMessage()    {}
func (*MsgSetBiographyResponse) XXX_MessageName() string {
	return "mirage.core.v1.MsgSetBiographyResponse"
}

func (m *MsgSetBiographyResponse) Marshal() (dAtA []byte, err error)    { return nil, nil }
func (m *MsgSetBiographyResponse) MarshalTo(dAtA []byte) (int, error)   { return 0, nil }
func (m *MsgSetBiographyResponse) Size() int                            { return 0 }
func (m *MsgSetBiographyResponse) Unmarshal(dAtA []byte) error          { return nil }
func (m *MsgSetBiographyResponse) MarshalToSizedBuffer([]byte) (int, error) { return 0, nil }

func init() {
	proto.RegisterType((*MsgSetBiography)(nil), "mirage.core.v1.MsgSetBiography")
	proto.RegisterType((*MsgSetBiographyResponse)(nil), "mirage.core.v1.MsgSetBiographyResponse")
}
