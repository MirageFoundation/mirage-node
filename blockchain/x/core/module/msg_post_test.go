package core

import (
	"strings"
	"testing"
)

func TestValidateMsgPostMedia(t *testing.T) {
	tests := []struct {
		name    string
		media   []string
		wantErr bool
		errMsg  string
	}{
		{
			name:    "Valid media (1 item)",
			media:   []string{"https://example.com/image.png"},
			wantErr: false,
		},
		{
			name:    "Valid media (multiple items)",
			media:   []string{"https://example.com/1.png", "https://example.com/2.mp4"},
			wantErr: false,
		},
		{
			name:    "Valid media (empty - backward compatibility)",
			media:   []string{},
			wantErr: false,
		},
		{
			name:    "Valid media (max items - 10)",
			media:   make([]string, 10),
			wantErr: false,
		},
		{
			name:    "Invalid media (too many items - 11)",
			media:   make([]string, 11),
			wantErr: true,
			errMsg:  "media exceeds limit",
		},
		{
			name:    "Invalid media (item too long)",
			media:   []string{"https://" + strings.Repeat("a", 2050)},
			wantErr: true,
			errMsg:  "exceeds length limit",
		},
		{
			name:    "Invalid media (not https)",
			media:   []string{"http://example.com/image.png"},
			wantErr: true,
			errMsg:  "must use https://",
		},
		{
			name:    "Invalid media (ftp)",
			media:   []string{"ftp://example.com/image.png"},
			wantErr: true,
			errMsg:  "must use https://",
		},
		{
			name:    "Invalid media (mixed valid and invalid)",
			media:   []string{"https://valid.com", "http://invalid.com"},
			wantErr: true,
			errMsg:  "must use https://",
		},
	}

	// Setup valid media for max items test
	for i := 0; i < 10; i++ {
		tests[3].media[i] = "https://example.com/image.png"
	}
	// Setup valid media for too many items test (to ensure it fails on count, not content)
	for i := 0; i < 11; i++ {
		tests[4].media[i] = "https://example.com/image.png"
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateMsgPostMedia(tt.media)
			if tt.wantErr {
				if err == nil {
					t.Errorf("validateMsgPostMedia() error = nil, wantErr %v", tt.wantErr)
					return
				}
				if tt.errMsg != "" && !strings.Contains(err.Error(), tt.errMsg) {
					t.Errorf("validateMsgPostMedia() error = %v, want error containing %v", err, tt.errMsg)
				}
			} else {
				if err != nil {
					t.Errorf("validateMsgPostMedia() error = %v, wantErr %v", err, tt.wantErr)
				}
			}
		})
	}
}
