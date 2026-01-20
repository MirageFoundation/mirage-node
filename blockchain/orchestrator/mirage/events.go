package mirage

import (
	"context"
	"fmt"
	"strings"

	abci "github.com/cometbft/cometbft/abci/types"
	tmtypes "github.com/cometbft/cometbft/types"

	"mirage/orchestrator/chains"
)

const bridgeBurnQuery = "tm.event='Tx' AND bridge_burn.burn_id EXISTS"

func (c *Client) WatchBridgeBurns(ctx context.Context, out chan<- chains.MirageBurnEvent) error {
	if out == nil {
		return fmt.Errorf("output channel cannot be nil")
	}
	if err := c.rpcClient.Start(); err != nil {
		return fmt.Errorf("failed to start rpc client: %w", err)
	}
	sub, err := c.rpcClient.Subscribe(ctx, "orchestrator-bridge-burn", bridgeBurnQuery)
	if err != nil {
		return fmt.Errorf("failed to subscribe to bridge burn events: %w", err)
	}

	c.logger.Printf("DEBUG subscribed to bridge_burn events")

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case msg, ok := <-sub:
			if !ok {
				return fmt.Errorf("bridge burn subscription closed")
			}
			data, ok := msg.Data.(tmtypes.EventDataTx)
			if !ok {
				c.logger.Printf("DEBUG unexpected event data type: %T", msg.Data)
				continue
			}
			eventMap := abciEventsToMap(data.Result.Events)
			burns, err := parseBridgeBurnEvents(eventMap)
			if err != nil {
				return err
			}
			for _, burn := range burns {
				select {
				case out <- burn:
					c.logger.Printf("DEBUG bridge burn received burn_id=%s dest_chain=%s amount=%d fee=%d net=%d", burn.BurnID, burn.DestinationChain, burn.Amount, burn.BridgeFee, burn.Amount-burn.BridgeFee)
				case <-ctx.Done():
					return ctx.Err()
				}
			}
		}
	}
}

// abciEventsToMap converts ABCI events to a map of type.key -> values
func abciEventsToMap(events []abci.Event) map[string][]string {
	result := make(map[string][]string)
	for _, event := range events {
		for _, attr := range event.Attributes {
			key := event.Type + "." + attr.Key
			result[key] = append(result[key], attr.Value)
		}
	}
	return result
}

func parseBridgeBurnEvents(events map[string][]string) ([]chains.MirageBurnEvent, error) {
	burnIDs := events["bridge_burn.burn_id"]
	if len(burnIDs) == 0 {
		return nil, nil
	}
	destChains := events["bridge_burn.destination_chain"]
	destAddrs := events["bridge_burn.destination_address"]
	amounts := events["bridge_burn.amount"]
	bridgeFees := events["bridge_burn.bridge_fee"]
	owners := events["bridge_burn.owner"]
	sequences := events["bridge_burn.sequence"]

	if len(destChains) != len(burnIDs) || len(destAddrs) != len(burnIDs) || len(amounts) != len(burnIDs) || len(owners) != len(burnIDs) || len(sequences) != len(burnIDs) || len(bridgeFees) != len(burnIDs) {
		return nil, fmt.Errorf("bridge burn event attribute mismatch: burn_ids=%d chains=%d addresses=%d amounts=%d fees=%d owners=%d sequences=%d",
			len(burnIDs), len(destChains), len(destAddrs), len(amounts), len(bridgeFees), len(owners), len(sequences))
	}

	burns := make([]chains.MirageBurnEvent, 0, len(burnIDs))
	for i, burnID := range burnIDs {
		amount, err := parseUint64(amounts[i], "bridge_burn.amount")
		if err != nil {
			return nil, err
		}
		bridgeFee, err := parseUint64(bridgeFees[i], "bridge_burn.bridge_fee")
		if err != nil {
			return nil, err
		}
		sequence, err := parseUint64(sequences[i], "bridge_burn.sequence")
		if err != nil {
			return nil, err
		}
		burns = append(burns, chains.MirageBurnEvent{
			BurnID:             strings.ToLower(strings.TrimSpace(burnID)),
			DestinationChain:   strings.TrimSpace(destChains[i]),
			DestinationAddress: strings.TrimSpace(destAddrs[i]),
			Amount:             amount,
			BridgeFee:          bridgeFee,
			Owner:              strings.TrimSpace(owners[i]),
			Sequence:           sequence,
		})
	}
	return burns, nil
}
