package app

import coretypes "mirage/x/core/types"

func appendPostPayload(w *canonWriter, m *coretypes.MsgPost) {
	w.writeString(100, m.Target)
	w.writeString(101, m.Community)
	w.writeString(102, m.Title)
	w.writeString(103, m.Content)
	w.writeString(104, m.Tag)
	for _, media := range m.Media {
		w.writeString(105, media)
	}
	if m.ProtocolVersion != 0 {
		w.writeUvarint(106, uint64(m.ProtocolVersion))
	}
}

func appendSubscribePayload(w *canonWriter, m *coretypes.MsgSubscribe) {
	w.writeUvarint(100, uint64(uint32(m.Level)))
	if m.Target != "" {
		w.writeString(101, m.Target)
	}
	if m.PeriodCount != 0 {
		w.writeUvarint(102, uint64(m.PeriodCount))
	}
}
