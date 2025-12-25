package types

// DefaultGenesis returns the default GenesisState for the core module.
func DefaultGenesis() *GenesisState {
	return &GenesisState{Params: DefaultParams()}
}

// Validate validates the GenesisState.
func (gs GenesisState) Validate() error { return gs.Params.Validate() }
