/*============= START OF PAGINATION =============*/
document.addEventListener('DOMContentLoaded', function() {

    // --- 1. CORE LOGIC: Update URL based on UI State ---
    const updateFilters = () => {
        const searchVal = document.getElementById('table-search')?.value.trim();
        const limitVal = document.getElementById('row-limit-select')?.value;
        // Added these two lines to capture the filter values
        const typeVal = document.getElementById('type-filter')?.value;
        const fulfillmentVal = document.getElementById('fulfillment-filter')?.value;

        const urlParams = new URLSearchParams();
        
        if (searchVal) urlParams.set('q', searchVal);
        if (limitVal) urlParams.set('limit', limitVal);
        // Added these to append the filters to the URL
        if (typeVal) urlParams.set('type', typeVal);
        if (fulfillmentVal) urlParams.set('fulfillment', fulfillmentVal);
        
        // Reset to page 1 on any filter change
        urlParams.set('page', 1);

        window.location.href = window.location.pathname + '?' + urlParams.toString();
    };

    // --- 2. SEARCH: Debounced Input ---
    const searchInput = document.getElementById('table-search');
    let searchTimer;
    if (searchInput) {
        searchInput.addEventListener('keyup', (e) => {
            clearTimeout(searchTimer);
            if (e.key === 'Enter') {
                updateFilters();
            } else {
                searchTimer = setTimeout(updateFilters, 800);
            }
        });
    }

    // --- 3. DROPDOWNS: Change Listeners ---
    const limitSelect = document.getElementById('row-limit-select');
    if (limitSelect) limitSelect.addEventListener('change', updateFilters);
    
    // Added listeners for the Type and Fulfillment filters
    const typeFilter = document.getElementById('type-filter');
    if (typeFilter) typeFilter.addEventListener('change', updateFilters);
    
    const fulfillmentFilter = document.getElementById('fulfillment-filter');
    if (fulfillmentFilter) fulfillmentFilter.addEventListener('change', updateFilters);

    // --- 4. CLEAR BUTTON: Click Listener ---
    const clearBtn = document.getElementById('clear-filters-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            window.location.href = window.location.pathname;
        });
    }

    // --- 5. JUMP TO PAGE: Logic & Listeners ---
    const jumpBtn = document.querySelector('.jump-btn');
    const jumpInput = document.getElementById('jump-page-input');

    const handleJump = () => {
        const page = parseInt(jumpInput.value);
        const maxPage = parseInt(jumpInput.getAttribute('max'));
        
        if (page >= 1 && page <= maxPage) {
            const urlParams = new URLSearchParams(window.location.search);
            urlParams.set('page', page);
            window.location.href = window.location.pathname + '?' + urlParams.toString();
        } else {
            jumpInput.style.borderColor = "#ef4444";
            setTimeout(() => jumpInput.style.borderColor = "#cbd5e1", 2000);
        }
    };

    if (jumpBtn) jumpBtn.addEventListener('click', handleJump);
    if (jumpInput) {
        jumpInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleJump();
        });
        }


});

/*============= END OF PAGINATION =============*/

/*============= START OF REFILL PROCESS =============*/
document.addEventListener('DOMContentLoaded', () => {
    const refillSearchInput = document.getElementById('refill-search-input');
    const refillDropdown = document.getElementById('refill-customer-dropdown-list');
    const refillOptions = document.querySelectorAll('.refill-option-item');
    const refillIdInput = document.getElementById('refill-customer-id');
    const noMatch = document.getElementById('no-refill-customer-match');
    const unregNameInput = document.querySelector('input[name="unregistered_customer_name"]');

    const tankSelect = document.getElementById('refill-tank-size');
    const tankText = document.getElementById('refill-tank-text');
    const labelReg = document.getElementById('label-tank-registered');
    const labelUnreg = document.getElementById('label-tank-unregistered');
    
    const quantityInput = document.getElementById('refill-quantity');
    const dynamicRowsContainer = document.getElementById('refill-dynamic-rows-container');

    // Parse active oxygen rentals JSON dataset from template
    let activeOxygenRentals = [];
    try {
        const scriptTag = document.getElementById('active-oxygen-rentals-data');
        if (scriptTag) {
            activeOxygenRentals = JSON.parse(scriptTag.textContent);
        }
    } catch (e) {
        console.error("Failed to parse active oxygen rentals JSON", e);
    }

    // Parse refillable products JSON dataset from template for unregistered dropdowns
    let refillableProducts = [];
    try {
        const scriptTag = document.getElementById('refillable-products-data');
        if (scriptTag) {
            refillableProducts = JSON.parse(scriptTag.textContent);
        }
    } catch (e) {
        // Fallback or read from existing select options if no separate JSON script tag exists
        refillableProducts = Array.from(tankSelect.options).map(opt => opt.value);
    }

    function renderDynamicRows() {
        const qty = Math.max(1, parseInt(quantityInput.value) || 1);
        const buyerType = document.querySelector('input[name="refill_buyer_type"]:checked').value;
        const isRegistered = buyerType === 'registered';
        const currentCustomerId = refillIdInput.value;

        // Capture existing values before clearing to prevent loss on input change
        const existingRows = Array.from(dynamicRowsContainer.children);
        const savedValues = existingRows.map(row => {
            const select = row.querySelector('select[name="swapped_rental_serial"]');
            const selectUnregProd = row.querySelector('select[name="unregistered_product_size"]');
            const inputEmpty = row.querySelector('input[name="empty_serial_numbers"]');
            const inputFull = row.querySelector('input[name="serial_numbers"]');
            return {
                selectedRental: select ? select.value : '',
                selectedUnregProd: selectUnregProd ? selectUnregProd.value : '',
                emptySerial: inputEmpty ? inputEmpty.value : '',
                incomingSerial: inputFull ? inputFull.value : ''
            };
        });

        dynamicRowsContainer.innerHTML = '';

        if (!isRegistered) {
            // Build dropdown options for products/sizes
            let productOptionsHtml = '<option value="">Select tank size...</option>';
            if (refillableProducts.length > 0 && typeof refillableProducts[0] === 'object') {
                refillableProducts.forEach(prod => {
                    productOptionsHtml += `<option value="${prod.name} - ${prod.size}">${prod.name} - ${prod.size}</option>`;
                });
            } else {
                Array.from(tankSelect.options).forEach(opt => {
                    productOptionsHtml += `<option value="${opt.value}">${opt.textContent.trim()}</option>`;
                });
            }

            for (let i = 1; i <= qty; i++) {
                const prevData = savedValues[i - 1] || { selectedUnregProd: '', emptySerial: '', incomingSerial: '' };
                const row = document.createElement('div');
                row.style.cssText = 'display: flex; flex-direction: column; gap: 8px; width: 100%; background: #f8fafc; padding: 12px; border-radius: 6px; border: 1px solid #e2e8f0; box-sizing: border-box; margin-bottom: 10px;';
                
                let currentProdOpts = productOptionsHtml;
                if (prevData.selectedUnregProd) {
                    currentProdOpts = currentProdOpts.replace(`value="${prevData.selectedUnregProd}"`, `value="${prevData.selectedUnregProd}" selected`);
                }

                row.innerHTML = `
                    <div class="form-field" style="margin-bottom: 0;">
                        <label style="font-weight: 700; color: #1e293b; margin-bottom: 4px; display: block; font-size: 0.8rem;">Tank Product & Size #${i}</label>
                        <select name="unregistered_product_size" class="medical-select" required
                                style="width: 100%; height: 38px; padding: 0 10px; background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; color: #1e293b; font-size: 0.85rem; outline: none; box-sizing: border-box;">
                            ${currentProdOpts}
                        </select>
                    </div>
                    <div style="display: flex; gap: 10px; width: 100%;">
                        <div style="flex: 1; min-width: 0;">
                            <label style="font-weight: 700; color: #1e293b; margin-bottom: 4px; display: block; font-size: 0.8rem;">Empty Tank Serial #${i}</label>
                            <input type="text" name="empty_serial_numbers" value="${prevData.emptySerial}" placeholder="e.g. ET-9021" required 
                                style="width: 100%; height: 38px; padding: 0 10px; background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; color: #1e293b; font-size: 0.85rem; outline: none; box-sizing: border-box;">
                        </div>
                        <div style="flex: 1; min-width: 0;">
                            <label style="font-weight: 700; color: #1e293b; margin-bottom: 4px; display: block; font-size: 0.8rem;">Full Tank Serial #${i} (Full)</label>
                            <input type="text" name="serial_numbers" value="${prevData.incomingSerial}" placeholder="e.g. FT-4412" required 
                                style="width: 100%; height: 38px; padding: 0 10px; background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; color: #1e293b; font-size: 0.85rem; outline: none; box-sizing: border-box;">
                        </div>
                    </div>
                `;
                dynamicRowsContainer.appendChild(row);
            }
            return;
        }

        const customerRentals = activeOxygenRentals.filter(r => String(r.customer_id) === String(currentCustomerId));

        for (let i = 1; i <= qty; i++) {
            const prevData = savedValues[i - 1] || { selectedRental: '', incomingSerial: '' };
            const row = document.createElement('div');
            row.style.cssText = 'display: flex; gap: 10px; width: 100%; background: #f8fafc; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; align-items: flex-end; box-sizing: border-box;';
            
            let rentalOptionsHtml = '<option value="">Select tank to return...</option>';
            customerRentals.forEach(rental => {
                const isSelected = rental.serial_number === prevData.selectedRental ? 'selected' : '';
                rentalOptionsHtml += `<option value="${rental.serial_number}" ${isSelected}>${rental.product_name} (${rental.product_size}) - SN: ${rental.serial_number}</option>`;
            });

            row.innerHTML = `
                <div style="flex: 1.1; min-width: 0;">
                    <label style="font-weight: 700; color: #1e293b; margin-bottom: 4px; display: block; font-size: 0.8rem;">Empty Tank #${i} (SN.)</label>
                    <select name="swapped_rental_serial" class="medical-select" required
                            style="width: 100%; height: 38px; padding: 0 10px; background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; color: #1e293b; font-size: 0.85rem; outline: none; box-sizing: border-box;">
                        ${rentalOptionsHtml}
                    </select>
                </div>
                <div style="flex: 0.9; min-width: 0;">
                    <label style="font-weight: 700; color: #1e293b; margin-bottom: 4px; display: block; font-size: 0.8rem;">Full Tank #${i} (SN.)</label>
                    <input type="text" name="serial_numbers" value="${prevData.incomingSerial}" placeholder="e.g. OX-NEW0${i}" required 
                        style="width: 100%; height: 38px; padding: 0 12px; background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; color: #1e293b; font-size: 0.85rem; outline: none; box-sizing: border-box;">
                </div>
            `;
            dynamicRowsContainer.appendChild(row);
        }
    }

    // 1. Toggle Buyer Type UI
    document.querySelectorAll('input[name="refill_buyer_type"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const isRegistered = e.target.value === 'registered';
            
            document.getElementById('refill-registered-group').style.display = isRegistered ? 'block' : 'none';
            document.getElementById('refill-unregistered-group').style.display = isRegistered ? 'none' : 'block';
            
            if (isRegistered) {
                unregNameInput.value = '';
            } else {
                refillSearchInput.value = '';
                refillIdInput.value = '';
            }
            
            if (isRegistered) {
                tankSelect.style.display = 'block';
                tankSelect.setAttribute('name', 'tank_size');
                tankText.style.display = 'none';
                tankText.removeAttribute('name');
                labelReg.style.display = 'inline';
                labelUnreg.style.display = 'none';
            } else {
                tankSelect.style.display = 'none';
                tankSelect.removeAttribute('name');
                tankText.style.display = 'none';
                tankText.removeAttribute('name');
                labelReg.style.display = 'none';
                labelUnreg.style.display = 'none';
            }
            renderDynamicRows();
        });
    });

    // 2. Search Filter for Customers
    refillSearchInput.addEventListener('input', () => {
        const term = refillSearchInput.value.toLowerCase();
        refillDropdown.classList.remove('hidden');
        let hasMatch = false;

        refillOptions.forEach(opt => {
            const matches = opt.dataset.searchString.includes(term);
            opt.style.display = matches ? 'flex' : 'none';
            if (matches) hasMatch = true;
        });
        noMatch.style.display = hasMatch ? 'none' : 'block';
    });

    // 3. Selection of Customer
    refillOptions.forEach(opt => {
        opt.addEventListener('click', () => {
            refillSearchInput.value = opt.dataset.name;
            refillIdInput.value = opt.dataset.id;
            refillDropdown.classList.add('hidden');
            renderDynamicRows();
        });
    });

    // 4. Quantity Change Event
    quantityInput.addEventListener('input', renderDynamicRows);
    quantityInput.addEventListener('change', renderDynamicRows);

    // 5. Close dropdown when clicking outside
    document.addEventListener('click', (event) => {
        if (!refillSearchInput.contains(event.target) && !refillDropdown.contains(event.target)) {
            refillDropdown.classList.add('hidden');
        }
    });

    // 6. Initialize UI state on page load
    const checkedRadio = document.querySelector('input[name="refill_buyer_type"]:checked');
    if (checkedRadio) {
        checkedRadio.dispatchEvent(new Event('change'));
    }
});

document.addEventListener("DOMContentLoaded", function() {
    const regRadio = document.getElementById("refill-buyer-registered");
    const unregRadio = document.getElementById("refill-buyer-unregistered");
    const tankContainer = document.getElementById("refill-tank-selection-container");

    function updateTankVisibility() {
        if (regRadio.checked) {
            tankContainer.style.display = "none";
        } else {
            tankContainer.style.display = "none";
        }
    }

    if (regRadio && unregRadio && tankContainer) {
        regRadio.addEventListener("change", updateTankVisibility);
        unregRadio.addEventListener("change", updateTankVisibility);
        updateTankVisibility();
    }
});
/*============= END OF REFILL PROCESS =============*/

/*============= START OF TRANSACTION MODAL =============*/

document.addEventListener('DOMContentLoaded', () => {

    // 1. Elements
    const openBtn = document.getElementById('open-txn-selection');
    const closeBtn = document.getElementById('close-selection-modal');
    const selectionModal = document.getElementById('txnSelectionModal');

    // ===============================
    // OPEN MODAL
    // ===============================
    if (openBtn) {
        openBtn.addEventListener('click', () => {
            if (selectionModal) {
                selectionModal.classList.remove('hidden');
            }
        });
    }

    // ===============================
    // CLOSE MODAL
    // ===============================
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            if (selectionModal) {
                selectionModal.classList.add('hidden');
            }
        });
    }

    // ===============================
    // TRANSACTION TYPE HANDLING
    // ===============================
    document.querySelectorAll('[data-flow]').forEach(button => {
        button.addEventListener('click', function (e) {

            // 🔥 PREVENT DOUBLE TRIGGER
            if (this.dataset.clicked === "1") return;
            this.dataset.clicked = "1";

            setTimeout(() => {
                this.dataset.clicked = "0";
            }, 300);

            const flowType = this.getAttribute('data-flow');

            // CLOSE TRANSACTION SELECTION MODAL
            if (selectionModal) {
                selectionModal.classList.add('hidden');
            }

            // ===============================
            // R E N T A L
            // ===============================
            if (flowType === 'Rental') {
                const rentModal = document.getElementById('rentAssetModal');
                if (rentModal) {
                    rentModal.classList.remove('hidden');
                }
            }

            // ===============================
            // R E F I L L 
            // ===============================
            else if (flowType === 'Refill') {
                const refillModal = document.getElementById('refillAssetModal');
                if (refillModal) {
                    // Clear previous entries out cleanly before showing
                    const serialInput = document.getElementById('refill-serial-number');
                    if (serialInput) serialInput.value = "";
                    
                    refillModal.classList.remove('hidden');
                }
            }

            // ===============================
            // P U R C H A S E (S A L E)
            // ===============================
            else if (flowType === 'Sale') {
                const purchaseModal = document.getElementById('purchaseAssetModal');
                if (purchaseModal) {
                    purchaseModal.classList.remove('hidden');
                }
            }

            // ===============================
            // P R I M E G A S
            // ===============================
            else if (flowType === 'Primegas') {
                // Adjust ID to match your secondary target modal setup if named differently
                const primegasModal = document.getElementById('primegasAssetModal');
                if (primegasModal) {
                    primegasModal.classList.remove('hidden');
                }
            }
        });
    });

    // ========================================================
    // SECURE CSP CLOSE LISTENERS & FORM RESET FOR REFILL MODAL
    // ========================================================
    document.addEventListener('click', function (event) {
        const targetBtn = event.target.closest('#close-refill-modal, #cancel-refill-modal');
        if (targetBtn) {
            const refillModal = document.getElementById('refillAssetModal');
            if (refillModal) {
                // 1. Close the modal layout
                refillModal.classList.add('hidden');
                
                // 2. Safely find and reset all form inputs to default values
                const refillForm = document.getElementById('refill-transaction-form');
                if (refillForm) {
                    refillForm.reset();
                }
            }
        }
    });
});

/*============= END OF TRANSACTION MODAL =============*/


/*============= PURCHASE SUBMISSION LOGIC =============*/

document.addEventListener('DOMContentLoaded', function() {
    const purchaseForm = document.getElementById('purchaseEntryForm');
    const purchaseModal = document.getElementById('purchaseAssetModal'); 

    // Array storage tracking multi-product data in the selection basket
    let purchaseBasket = [];

    /*============= CUSTOMER SELECTION & CLASSIFICATION LOGIC =============*/
    const radioRegistered = document.getElementById('buyer-type-registered');
    const radioUnregistered = document.getElementById('buyer-type-unregistered'); // Matches HTML id
    const registeredBuyerGroup = document.getElementById('registered-buyer-group');
    const unregisteredBuyerGroup = document.getElementById('unregistered-buyer-group'); // Matches HTML id

    const customerSearchInput = document.getElementById('purchase-customer-search'); // Matches HTML id
    const customerDropdownList = document.getElementById('purchase-customer-dropdown-list');
    const selectedCustomerId = document.getElementById('purchase-customer-id');
    const customNameInput = document.getElementById('purchase-custom-name'); // Matches HTML id

    const bannerName = document.getElementById('purchase-banner-buyer-name');
    const badge = document.getElementById('purchase-customer-type-display');

    // Dynamic visibility toggling for Client Classification Track
    function handleBuyerTypeChange() {
        if (radioRegistered && radioRegistered.checked) {
            if (registeredBuyerGroup) registeredBuyerGroup.style.display = 'block';
            if (unregisteredBuyerGroup) unregisteredBuyerGroup.style.display = 'none';
            if (customNameInput) customNameInput.value = '';
            bannerName.textContent = customerSearchInput.value.trim() || "Enter Buyer Information";
            badge.textContent = "New Transaction";
        } else if (radioUnregistered && radioUnregistered.checked) {
            if (unregisteredBuyerGroup) unregisteredBuyerGroup.style.display = 'block';
            if (registeredBuyerGroup) registeredBuyerGroup.style.display = 'none';
            if (selectedCustomerId) selectedCustomerId.value = '';
            if (customerSearchInput) customerSearchInput.value = '';
            bannerName.textContent = customNameInput.value.trim() || "Walk-In Customer";
            badge.textContent = "Unregistered";
        }
    }

    radioRegistered?.addEventListener('change', handleBuyerTypeChange);
    radioUnregistered?.addEventListener('change', handleBuyerTypeChange);

    // Update banner display in real-time when typing a custom walk-in name
    customNameInput?.addEventListener('input', function() {
        if (bannerName) {
            bannerName.textContent = this.value.trim() || "Walk-In Customer";
        }
    });

    // Open dropdown container on focus or explicit click interaction
    const showCustomerDropdown = () => {
        customerDropdownList?.classList.remove('hidden');
        filterRegisteredCustomers();
    };
    customerSearchInput?.addEventListener('focus', showCustomerDropdown);
    customerSearchInput?.addEventListener('click', showCustomerDropdown);

    // Reset hidden ID on manual input typing to prevent mismatched submission data
    customerSearchInput?.addEventListener('input', () => {
        if (selectedCustomerId) {
            selectedCustomerId.value = '';
        }
        if (bannerName) {
            bannerName.textContent = customerSearchInput.value.trim() || "Enter Buyer Information";
        }
        filterRegisteredCustomers();
    });

    function filterRegisteredCustomers() {
        if (!customerSearchInput) return;
        const query = customerSearchInput.value.toLowerCase().trim();
        const options = document.querySelectorAll('.purchase-customer-option-item');
        let hasMatches = false;

        options.forEach(option => {
            const searchStr = (option.getAttribute('data-search-string') || '').toLowerCase();
            if (searchStr.includes(query)) {
                option.style.display = 'flex';
                hasMatches = true;
            } else {
                option.style.display = 'none';
            }
        });

        const noMatchDiv = document.getElementById('no-purchase-customer-match');
        if (noMatchDiv) {
            noMatchDiv.style.display = hasMatches ? 'none' : 'block';
        }
    }

    // Target customer selection assignment on dropdown list item click
    document.addEventListener('click', function(e) {
        const optionItem = e.target.closest('.purchase-customer-option-item');
        if (optionItem) {
            const id = optionItem.getAttribute('data-id');
            const name = optionItem.getAttribute('data-name');
            
            if (selectedCustomerId) selectedCustomerId.value = id;
            if (customerSearchInput) customerSearchInput.value = name;
            if (bannerName) bannerName.textContent = name;
            if (badge) badge.textContent = 'Registered Customer';
            
            customerDropdownList?.classList.add('hidden');
        }
    });

    /*============= HELPER CALCULATIONS UTILITIES =============*/
    function cleanFloat(val) {
        if (typeof val === 'number') return isNaN(val) ? 0 : val;
        if (!val) return 0;
        const cleaned = val.toString().replace(/[^0-9.-]/g, '');
        const parsed = parseFloat(cleaned);
        return isNaN(parsed) ? 0 : parsed;
    }

    function cleanInt(val) {
        if (typeof val === 'number') return isNaN(val) ? 0 : Math.floor(val);
        if (!val) return 0;
        const cleaned = val.toString().replace(/[^0-9-]/g, '');
        const parsed = parseInt(cleaned, 10);
        return isNaN(parsed) ? 0 : parsed;
    }

    /*============= DYNAMIC FORM VISIBILITY FIELD HANDLING =============*/
    purchaseForm?.addEventListener('change', function(e) {
        if (e.target.name === 'fulfillment_type') {
            const isDelivery = e.target.value === 'Delivery';
            togglePurchaseDelivery(isDelivery);
        }
        if (e.target.id === 'purchase-payment-method') {
            updatePurchaseRefVisibility();
        }
    });

    function togglePurchaseDelivery(isDelivery) {
        const deliveryFields = document.getElementById('purchase-delivery-fields');
        if (deliveryFields) {
            deliveryFields.style.display = isDelivery ? 'grid' : 'none';
            const addrInput = deliveryFields.querySelector('input[name="delivery_address"]');
            if (addrInput) addrInput.required = isDelivery;
        }
    }

    function updatePurchaseRefVisibility() {
        const purchasePaymentMethod = document.getElementById('purchase-payment-method');
        const purchaseRefGroup = document.getElementById('purchase-ref-group');
        if (purchasePaymentMethod && purchaseRefGroup) {
            const isElectronic = purchasePaymentMethod.value !== 'Cash';
            purchaseRefGroup.style.display = isElectronic ? 'block' : 'none';
            
            if (!isElectronic) {
                const refInput = purchaseRefGroup.querySelector('input');
                if (refInput) refInput.value = '';
            }
        }
    }

    /*============= LIVE BASKET MULTI-PRODUCT LOGIC =============*/
    const purchaseSearchInput = document.getElementById('purchase-product-search-input');
    const purchaseDropdownList = document.getElementById('purchase-product-dropdown-list');
    const purchaseBasketContainer = document.getElementById('purchase-selected-products-container');
    const purchaseEmptyPlaceholder = document.getElementById('purchase-empty-basket-placeholder');

    const showProductDropdown = () => {
        purchaseDropdownList?.classList.remove('hidden');
        filterPurchaseProducts();
    };
    purchaseSearchInput?.addEventListener('focus', showProductDropdown);
    purchaseSearchInput?.addEventListener('click', showProductDropdown);

    // Close search dropdown lists safely when clicking outside boundaries
    document.addEventListener('click', function(e) {
        if (purchaseSearchInput && purchaseDropdownList && !purchaseSearchInput.contains(e.target) && !purchaseDropdownList.contains(e.target)) {
            purchaseDropdownList.classList.add('hidden');
        }
        if (customerSearchInput && customerDropdownList && !customerSearchInput.contains(e.target) && !customerDropdownList.contains(e.target)) {
            customerDropdownList.classList.add('hidden');
        }
    });

    purchaseSearchInput?.addEventListener('input', filterPurchaseProducts);

    function filterPurchaseProducts() {
        if (!purchaseSearchInput) return;
        const query = purchaseSearchInput.value.toLowerCase().trim();
        const options = document.querySelectorAll('.purchase-product-option-item');
        let hasMatches = false;

        options.forEach(option => {
            const searchStr = (option.getAttribute('data-search-string') || '').toLowerCase();
            if (searchStr.includes(query)) {
                option.style.display = 'flex';
                hasMatches = true;
            } else {
                option.style.display = 'none';
            }
        });

        const noMatchDiv = document.getElementById('no-purchase-product-match');
        if (noMatchDiv) {
            noMatchDiv.style.display = hasMatches ? 'none' : 'block';
        }
    }

    // Add item option to basket selection container
    document.addEventListener('click', function(e) {
        const optionItem = e.target.closest('.purchase-product-option-item');
        if (optionItem) {
            const id = optionItem.getAttribute('data-id');
            const name = optionItem.getAttribute('data-name');
            const maxStock = cleanInt(optionItem.getAttribute('data-stock'));
            const price = cleanFloat(optionItem.getAttribute('data-price'));

            const existingItem = purchaseBasket.find(i => i.id === id);
            if (existingItem) {
                if (existingItem.quantity < maxStock) {
                    existingItem.quantity += 1;
                } else {
                    alert(`Cannot exceed maximum available stock layout limit (${maxStock}) for this item.`);
                }
            } else {
                purchaseBasket.push({ id, name, maxStock, price, quantity: 1 });
            }

            if (purchaseSearchInput) purchaseSearchInput.value = '';
            purchaseDropdownList?.classList.add('hidden');
            renderPurchaseBasketUI();
        }
    });

    function renderPurchaseBasketUI() {
        if (!purchaseBasketContainer) return;

        const rows = purchaseBasketContainer.querySelectorAll('.basket-item-row');
        rows.forEach(r => r.remove());

        if (purchaseBasket.length === 0) {
            purchaseEmptyPlaceholder?.classList.remove('hidden');
        } else {
            purchaseEmptyPlaceholder?.classList.add('hidden');

            purchaseBasket.forEach((item, index) => {
                const itemRow = document.createElement('div');
                itemRow.className = 'basket-item-row';
                itemRow.style = 'display: flex; align-items: center; justify-content: space-between; gap: 12px; background: white; border: 1px solid #e2e8f0; padding: 8px 12px; border-radius: 6px;';
                itemRow.innerHTML = `
                    <div style="flex: 1;">
                        <strong style="font-size: 13px; color: #1e293b; display:block;">${item.name}</strong>
                        <span style="font-size: 11px; color: #64748b;">₱${item.price.toFixed(2)} each</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <label style="font-size: 11px; color: #64748b;">Qty:</label>
                        <input type="number" class="clinical-input basket-qty-input" data-index="${index}" min="1" max="${item.maxStock}" value="${item.quantity}" style="width: 65px; height: 32px; padding: 0 6px; text-align: center;">
                    </div>
                    <button type="button" class="remove-basket-item-btn" data-index="${index}" style="background: none; border: none; color: #ef4444; cursor: pointer; display: flex; align-items: center;">
                        <span class="material-symbols-rounded" style="font-size: 18px;">delete</span>
                    </button>
                `;
                purchaseBasketContainer.appendChild(itemRow);
            });
        }
        updatePurchaseBillingSummary();
    }

    purchaseBasketContainer?.addEventListener('input', function(e) {
        if (e.target.classList.contains('basket-qty-input')) {
            const idx = cleanInt(e.target.getAttribute('data-index'));
            let val = cleanInt(e.target.value) || 1;
            const maxLimit = purchaseBasket[idx].maxStock;

            if (val > maxLimit) {
                alert(`Only ${maxLimit} items available in storage inventory logs.`);
                val = maxLimit;
                e.target.value = val;
            } else if (val < 1) {
                val = 1;
                e.target.value = val;
            }
            purchaseBasket[idx].quantity = val;
            updatePurchaseBillingSummary();
        }
    });

    purchaseBasketContainer?.addEventListener('click', function(e) {
        const deleteBtn = e.target.closest('.remove-basket-item-btn');
        if (deleteBtn) {
            const idx = cleanInt(deleteBtn.getAttribute('data-index'));
            purchaseBasket.splice(idx, 1);
            renderPurchaseBasketUI();
        }
    });

/*============= FINANCIAL AND CALCULATIONS LOGIC =============*/
    const amountPaidInput = document.getElementById('purchase-amount-paid');
    const voucherInput = document.getElementById('purchase-voucher-amount');
    
    amountPaidInput?.addEventListener('input', updatePurchaseBillingSummary);
    voucherInput?.addEventListener('input', updatePurchaseBillingSummary);

    function updatePurchaseBillingSummary() {
        const countText = document.getElementById('purchase-items-count-text');
        const grossBillDisplay = document.getElementById('purchase-gross-bill');
        const summaryPaidDisplay = document.getElementById('purchase-summary-paid-val');
        const totalDisplay = document.getElementById('purchase-total-display');
        const breakdownContainer = document.getElementById('purchase-summary-items-breakdown');

        let totalItemsCount = 0;
        let grossTotalContract = 0;

        if (breakdownContainer) breakdownContainer.innerHTML = '';

        purchaseBasket.forEach(item => {
            const itemQty = cleanInt(item.quantity) || 1;
            const itemPrice = cleanFloat(item.price) || 0;
            const itemTotalCost = itemPrice * itemQty;

            totalItemsCount += itemQty;
            grossTotalContract += itemTotalCost;

            if (breakdownContainer) {
                const breakdownRow = document.createElement('div');
                breakdownRow.style = 'display: flex; justify-content: space-between; font-size: 12px; color: #64748b;';
                breakdownRow.innerHTML = `
                    <span>• ${item.name} <small>(${itemQty} × ₱${itemPrice.toLocaleString('en-US', {minimumFractionDigits: 2})})</small></span>
                    <span>₱${itemTotalCost.toLocaleString('en-US', {minimumFractionDigits: 2})}</span>
                `;
                breakdownContainer.appendChild(breakdownRow);
            }
        });

        if (countText) countText.innerText = `${totalItemsCount} Item(s) Selected`;
        if (grossBillDisplay) grossBillDisplay.innerText = `₱${grossTotalContract.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        // 1. Get and handle Voucher / Discount amount display
        let voucherAmount = cleanFloat(voucherInput?.value);
        const voucherSummaryRow = document.getElementById('purchase-voucher-summary-row');
        const voucherSummaryVal = document.getElementById('purchase-summary-voucher-val');

        if (voucherSummaryRow) {
            if (voucherAmount > 0) {
                voucherSummaryRow.style.display = 'flex';
                if (voucherSummaryVal) {
                    voucherSummaryVal.innerText = `- ₱${voucherAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                }
            } else {
                voucherSummaryRow.style.display = 'none';
            }
        }

        // 2. Calculate Net Total after voucher deduction (cannot be lower than 0)
        let netTotal = Math.max(0, grossTotalContract - voucherAmount);

        // 3. Handle Amount Paid auto-fill logic based on the net total
        let amountPaid = cleanFloat(amountPaidInput?.value);
        
        if (amountPaidInput && (amountPaidInput.value === "0.00" || amountPaidInput.value === "" || amountPaidInput.dataset.autoFilled === "true")) {
            amountPaid = netTotal;
            amountPaidInput.value = netTotal.toFixed(2);
            amountPaidInput.dataset.autoFilled = "true";
        }

        if (summaryPaidDisplay) summaryPaidDisplay.innerText = `- ₱${amountPaid.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        // 4. Calculate Remaining Balance using Net Total minus Amount Paid
        const remainingBalance = Math.max(0, netTotal - amountPaid);
        const balanceSubText = document.getElementById('purchase-balance-label');
        
        if (totalDisplay) {
            totalDisplay.innerText = `₱${remainingBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

            if (remainingBalance <= 0 && netTotal > 0) {
                totalDisplay.className = "total-amount-display status-paid";
                if (balanceSubText) {
                    balanceSubText.textContent = "Fully Settled";
                    balanceSubText.className = "status-paid";
                }
            } else if (amountPaid > 0) {
                totalDisplay.className = "total-amount-display status-pending";
                if (balanceSubText) {
                    balanceSubText.textContent = "Partial Balance Due";
                    balanceSubText.className = "status-pending";
                }
            } else {
                totalDisplay.className = "total-amount-display";
                if (balanceSubText) {
                    balanceSubText.textContent = "Remaining collectibles";
                    balanceSubText.className = "";
                }
            }
        }
    }

    amountPaidInput?.addEventListener('keydown', function() {
        this.dataset.autoFilled = "false";
    });

    /*============= MODAL RESET PROCEDURES =============*/
    function resetPurchaseModal() {
        purchaseBasket = [];
        if (purchaseForm) {
            purchaseForm.reset();
            togglePurchaseDelivery(false);
            updatePurchaseRefVisibility();
            if (radioRegistered) {
                radioRegistered.checked = true;
                handleBuyerTypeChange();
            }
        }
        if (amountPaidInput) amountPaidInput.dataset.autoFilled = "true";
        renderPurchaseBasketUI();
    }

    /*============= FORM SUBMISSION VERIFICATION PROCESS =============*/
    if (purchaseForm) {
        purchaseForm.addEventListener('submit', function(e) {
            e.preventDefault();

            const submitBtn = this.querySelector('button[type="submit"]');

            if (purchaseBasket.length === 0) {
                alert("Error: Please select at least one component or product item to purchase.");
                return;
            }

            const buyerTypeEle = this.querySelector('input[name="buyer_type"]:checked');
            const buyerType = buyerTypeEle ? buyerTypeEle.value : 'registered';
            
            if (buyerType === 'registered') {
                const customerId = document.getElementById('purchase-customer-id')?.value;
                const customerName = customerSearchInput?.value?.trim();
                
                if (!customerId || !customerName) {
                    alert("Please search and select the name of the customer from the options list.");
                    return;
                }
            } else {
                const walkInName = customNameInput?.value?.trim();
                if (!walkInName) {
                    alert("Please enter the name of the customer.");
                    return;
                }
            }

            // Temporarily inject the serialized basket items into a hidden form field 
            // so request.form can read it just like a traditional form submission.
            let itemsInput = this.querySelector('input[name="items"]');
            if (!itemsInput) {
                itemsInput = document.createElement('input');
                itemsInput.type = 'hidden';
                itemsInput.name = 'items';
                this.appendChild(itemsInput);
            }
            itemsInput.value = JSON.stringify(purchaseBasket.map(i => ({ 
                id: /^\d+$/.test(i.id) ? parseInt(i.id, 10) : i.id, 
                quantity: cleanInt(i.quantity), 
                price: cleanFloat(i.price) 
            })));

            submitBtn.disabled = true;
            submitBtn.innerText = "Processing Transaction...";

            // Submit as a standard form request so Flask's redirect() and flash() work normally
            this.submit();
        });
    }

    /*============= CLOSING EVENT ACTION HANDLERS =============*/
    document.addEventListener('click', function(e) {
        if (e.target.closest('.close-purchase-modal') || e.target === purchaseModal) {
            purchaseModal?.classList.add('hidden');
            resetPurchaseModal();
        }
    });
});

/*============= START OF RENTMODAL MULTI-PRODUCT SYSTEM =============*/

const rentModal = document.getElementById('rentAssetModal');
const rentBtns = document.querySelectorAll('.asset-action-btn.rent');
const rentPaymentMethod = document.getElementById('rent-payment-method');
const rentRefGroup = document.getElementById('rent-ref-group');

const productSearchInput = document.getElementById('product-search-input');
const productDropdownList = document.getElementById('product-dropdown-list');
const selectedProductsContainer = document.getElementById('selected-products-container');
const emptyBasketPlaceholder = document.getElementById('empty-basket-placeholder');

// RENT MODAL INLINE CUSTOMER SELECTION ELEMENTS
const rentCustomerInput = document.getElementById('rent-customer-search-input');
const rentCustomerDropdown = document.getElementById('rent-customer-dropdown-list');
const rentCustomerIdInput = document.getElementById('global-customer-id');
const rentPatientDisplayName = document.getElementById('rent-patient-display-name');

// INITIAL OXYGEN FILL CHECKBOX & AMOUNT PAID ELEMENTS
const fillAsPaidToggle = document.getElementById('rent-fill-as-paid-toggle');
const fillCostInput = document.getElementById('rent-fill-cost');
const amountPaidInput = document.getElementById('rent-amount-paid');

// Memory state cache keeping track of active selected basket items
let productBasket = [];

/**
 * Handles showing/hiding the reference field based on payment method
 */
function updateRentRefVisibility() {
    if (rentPaymentMethod && rentRefGroup) {
        const isElectronic = rentPaymentMethod.value !== 'Cash';
        rentRefGroup.style.display = isElectronic ? 'block' : 'none';
        
        if (!isElectronic) {
            const refInput = rentRefGroup.querySelector('input');
            if (refInput) refInput.value = '';
        }
    }
}

/**
 * FR02 / RULE-03: preview the distance-based delivery deposit.
 * The server recomputes the authoritative amount on submission.
 */
function updateRentDepositFromDistance() {
    const depositInput = document.getElementById('rent-customer-deposit');
    const distanceInput = document.getElementById('rent-distance-km');
    const hint = document.getElementById('rent-deposit-hint');
    if (!depositInput) return;

    const fallback = parseFloat(depositInput.dataset.flatDeposit || '0') || 0;
    let tiers = [];
    try {
        tiers = JSON.parse(depositInput.dataset.depositTiers || '[]');
    } catch (err) {
        tiers = [];
    }

    const km = distanceInput ? parseFloat(distanceInput.value) : NaN;
    const validDistance = !isNaN(km) && km > 0;
    let amount = 0;
    let label = 'Enter delivery distance';

    if (validDistance) {
        amount = fallback;
        label = 'Flat delivery deposit';

        const numericTiers = tiers
            .filter(tier => tier.max_km !== null && tier.max_km !== undefined)
            .sort((a, b) => Number(a.max_km) - Number(b.max_km));

        let matched = false;
        for (const tier of numericTiers) {
            if (km <= Number(tier.max_km)) {
                amount = Number(tier.amount);
                label = tier.label;
                matched = true;
                break;
            }
        }
        if (!matched) {
            const fallbackTier = tiers.find(
                tier => tier.max_km === null || tier.max_km === undefined
            );
            if (fallbackTier) {
                amount = Number(fallbackTier.amount);
                label = fallbackTier.label;
            }
        }
    }

    depositInput.value = amount.toFixed(2);
    if (hint) {
        hint.textContent = validDistance
            ? `Deposit: ₱${amount.toFixed(2)} (${label})`
            : 'Enter the delivery distance to compute the deposit.';
    }
}

/**
 * Handles toggling delivery fields and fees for the Rent Modal
 */
function toggleRentDelivery(isDelivery) {
    const deliveryFields = document.getElementById('rent-delivery-fields');
    const deliveryFeeInput = document.getElementById('rent-delivery-fee');
    
    if (deliveryFields) {
        deliveryFields.style.display = isDelivery ? 'grid' : 'none';
        const addrInput = deliveryFields.querySelector('input[name="delivery_address"]');
        if (addrInput) addrInput.required = isDelivery;

        const distanceInput = document.getElementById('rent-distance-km');
        if (distanceInput) {
            distanceInput.required = isDelivery;
            if (!isDelivery) distanceInput.value = '';
        }
    }

    // FR02 / RULE-03: delivery deposit is computed from the distance tiers.
    const depositInput = document.getElementById('rent-customer-deposit');
    const depositHint = document.getElementById('rent-deposit-hint');
    if (depositInput) {
        depositInput.readOnly = isDelivery;
        if (isDelivery) {
            updateRentDepositFromDistance();
        } else {
            depositInput.value = '0.00';
            if (depositHint) {
                depositHint.textContent = 'Walk-in rentals default to zero; staff may adjust.';
            }
        }
    }
    
    // Reset delivery fee dynamically if changing fulfillment back to Walk-In
    if (!isDelivery && deliveryFeeInput) {
        deliveryFeeInput.value = '0.00';
    }
    
    // Recalculate totals to account for added/removed delivery fees
    calculateRentalTotals();
}

/**
 * Resets the Global Customer Selection state
 */
function resetGlobalCustomerSelection() {
    if (rentCustomerInput) rentCustomerInput.value = '';
    if (rentCustomerIdInput) rentCustomerIdInput.value = '';
    if (rentPatientDisplayName) rentPatientDisplayName.textContent = 'No Patient Selected';
    
    if (rentCustomerDropdown) {
        rentCustomerDropdown.classList.add('hidden');
        const items = rentCustomerDropdown.querySelectorAll('.customer-option-item');
        items.forEach(item => item.style.display = 'flex');
        
        const noMatch = document.getElementById('no-customer-match');
        if (noMatch) noMatch.style.display = 'none';
    }
}

/**
 * Resets the Rent Modal state
 */
function resetRentModal() {
    const form = document.getElementById('rentEntryForm');
    if (form) {
        form.reset();
        toggleRentDelivery(false); 
        updateRentRefVisibility();
    }
    
    // Hide and reset oxygen fill section on modal reset
    const oxygenContainer = document.getElementById('oxygen-fill-container');
    if (oxygenContainer) oxygenContainer.style.display = 'none';
    
    const summaryFillRow = document.getElementById('summary-initial-fill-row');
    if (summaryFillRow) summaryFillRow.style.display = 'none';
    
    if (fillCostInput) fillCostInput.value = '0.00';
    if (fillAsPaidToggle) fillAsPaidToggle.checked = false;
    
    // Default duration setup
    const durationInput = document.getElementById('rent-duration-value');
    if (durationInput) durationInput.value = 1;

    const durationUnit = document.getElementById('rent-duration-unit');
    if (durationUnit) durationUnit.value = 'months';

    // Set default start date to today
    const startInput = document.getElementById('rent-start-date');
    if (startInput) {
        const today = new Date().toISOString().split('T')[0];
        startInput.value = today;
    }
    
    // Reset Delivery Fee to default value
    const deliveryFeeInput = document.getElementById('rent-delivery-fee');
    if (deliveryFeeInput) deliveryFeeInput.value = '0.00';
    
    productBasket = [];
    renderProductBasket();
    if (productSearchInput) productSearchInput.value = '';
    
    resetGlobalCustomerSelection();
    calculateRentalTotals();
}

/**
 * Helper to verify if an item is strictly oxygen-related equipment
 */
function isOxygenEquipment(item) {
    const itemNameLower = (item.name || "").toLowerCase();
    const itemCategoryLower = (item.category || "").toLowerCase();
    
    return (
        itemNameLower.includes('oxygen') || 
        itemNameLower.includes('o2') || 
        itemNameLower.includes('concentrator') ||
        itemCategoryLower.includes('oxygen')
    );
}

/**
 * Captures currently typed serial numbers from the DOM into the productBasket array
 */
function captureCurrentSerials() {
    if (!selectedProductsContainer) return;
    const rows = selectedProductsContainer.querySelectorAll('.selected-product-row');
    rows.forEach(row => {
        const qtyInput = row.querySelector('.basket-qty-input');
        if (!qtyInput) return;
        const productId = qtyInput.getAttribute('data-product-id');
        const targetItem = productBasket.find(i => String(i.id) === String(productId));
        
        if (targetItem) {
            const serialInputs = row.querySelectorAll('.oxygen-serial-field');
            targetItem.serials = [];
            serialInputs.forEach(input => {
                targetItem.serials.push(input.value);
            });
        }
    });
}

/**
 * Toggles the visibility of the initial oxygen fill cost container based on the basket
 */
function updateOxygenFillVisibility() {
    const oxygenContainer = document.getElementById('oxygen-fill-container');
    const summaryFillRow = document.getElementById('summary-initial-fill-row');
    
    const hasOxygen = productBasket.some(item => isOxygenEquipment(item));

    if (oxygenContainer) {
        if (hasOxygen) {
            oxygenContainer.style.display = 'block';
        } else {
            oxygenContainer.style.display = 'none';
            if (fillCostInput) fillCostInput.value = '0.00';
            if (fillAsPaidToggle) fillAsPaidToggle.checked = false;
            if (summaryFillRow) summaryFillRow.style.display = 'none';
            calculateRentalTotals();
        }
    }
}

/**
 * Renders the visible items added into the customer's equipment basket
 */
function renderProductBasket() {
    if (!selectedProductsContainer) return;

    // Capture existing serials before wiping DOM container HTML
    captureCurrentSerials();

    selectedProductsContainer.innerHTML = '';
    
    if (productBasket.length === 0) {
        if (emptyBasketPlaceholder) selectedProductsContainer.appendChild(emptyBasketPlaceholder);
        updateOxygenFillVisibility();
        calculateRentalTotals();
        return;
    }

    productBasket.forEach((item) => {
        const isOxygen = isOxygenEquipment(item);
        const qty = parseInt(item.quantity) || 1;

        const row = document.createElement('div');
        row.className = 'selected-product-row';
        row.style = 'display: flex; flex-direction: column; gap: 8px; background: white; padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,0.02); margin-bottom: 8px;';
        
        let rowInnerHtml = `
            <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
                <div style="display: flex; flex-direction: column; gap: 2px; flex: 1;">
                    <span style="font-weight: 600; font-size: 13px; color: #1e293b;">${item.name}</span>
                    <span style="font-size: 11px; color: #64748b;">₱${parseFloat(item.rentPrice).toLocaleString('en-US', {minimumFractionDigits: 2})}/month</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <input type="hidden" name="product_ids" value="${item.id}">
                    <input type="hidden" name="unit_price_${item.id}" value="${item.rentPrice}">
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <label style="font-size: 11px; color: #64748b;">Qty:</label>
                        <input type="number" name="quantity_${item.id}" class="clinical-input basket-qty-input" 
                               value="${qty}" min="1" max="${item.maxStock}" 
                               data-product-id="${item.id}" 
                               style="width: 60px; height: 32px; padding: 0 6px; font-size: 13px; text-align: center;">
                    </div>
                    <button type="button" class="btn-remove-basket-item" data-product-id="${item.id}" 
                            style="background: none; border: none; color: #ef4444; cursor: pointer; display: flex; align-items: center; padding: 4px;">
                        <span class="material-symbols-rounded" style="font-size: 18px;">delete</span>
                    </button>
                </div>
            </div>
        `;

        if (isOxygen) {
            let serialInputsHTML = `
                <div style="margin-top: 4px; padding-top: 6px; border-top: 1px dashed #cbd5e1; display: flex; flex-direction: column; gap: 4px;">
                    <small style="color: #0284c7; font-weight: 600; font-size: 11px;">Enter Serial Number(s) for Oxygen Unit(s):</small>
            `;

            for (let i = 0; i < qty; i++) {
                const existingSerial = (item.serials && item.serials[i]) ? item.serials[i] : '';
                serialInputsHTML += `
                    <input type="text" name="serial_number_${item.id}_${i}" 
                           class="clinical-input oxygen-serial-field" 
                           style="height: 32px; font-size: 12px; padding: 0 8px;" 
                           placeholder="Oxygen Tank Serial # for unit ${i + 1}" 
                           value="${existingSerial}" required>
                `;
            }
            serialInputsHTML += `</div>`;
            rowInnerHtml += serialInputsHTML;
        }

        row.innerHTML = rowInnerHtml;
        selectedProductsContainer.appendChild(row);
    });

    updateOxygenFillVisibility();
    calculateRentalTotals();
}

// Listen for quantity changes inside the selected equipment basket
if (selectedProductsContainer) {
    selectedProductsContainer.addEventListener('input', function(e) {
        if (e.target && e.target.classList.contains('basket-qty-input')) {
            const productId = e.target.getAttribute('data-product-id');
            let newQty = parseInt(e.target.value) || 1;
            const max = parseInt(e.target.max) || 999;
            
            if (newQty > max) newQty = max;
            if (newQty < 1) newQty = 1;
            
            const targetItem = productBasket.find(i => String(i.id) === String(productId));
            if (targetItem) {
                targetItem.quantity = newQty;
                renderProductBasket();
                
                const activeInput = selectedProductsContainer.querySelector(`input[data-product-id="${productId}"].basket-qty-input`);
                if (activeInput) {
                    activeInput.focus();
                    activeInput.setSelectionRange(activeInput.value.length, activeInput.value.length);
                }
            }
        }
    });
}

/**
 * Processes parameter matches dynamically to compute billing abstracts and forward return date calculations
 */
function calculateRentalTotals() {
    const startInput = document.getElementById('rent-start-date');
    const durationInput = document.getElementById('rent-duration-value');
    const durationUnitInput = document.getElementById('rent-duration-unit');
    const hiddenReturnInput = document.getElementById('rent-return-date');
    const previewReturnText = document.getElementById('rent-return-date-preview');
    const voucherInput = document.getElementById('rent-voucher-amount');
    const deliveryFeeInput = document.getElementById('rent-delivery-fee');
    const breakdownContainer = document.getElementById('rent-summary-items-breakdown');

    let voucherAmount = voucherInput ? (parseFloat(voucherInput.value) || 0) : 0;
    const deliveryFee = deliveryFeeInput ? (parseFloat(deliveryFeeInput.value) || 0) : 0;
    const fillCost = fillCostInput && fillCostInput.offsetParent !== null ? (parseFloat(fillCostInput.value) || 0) : 0;
    const isFillChecked = fillAsPaidToggle ? fillAsPaidToggle.checked : false;
    
    // Read exact amount paid entered by user
    let totalAmountPaid = amountPaidInput ? (parseFloat(amountPaidInput.value) || 0) : 0;

    let durationVal = durationInput ? (parseInt(durationInput.value) || 1) : 1;
    if (durationVal < 1) durationVal = 1;
    
    const durationUnit = durationUnitInput ? durationUnitInput.value : 'months';

    if (startInput && startInput.value) {
        const parts = startInput.value.split('-');
        if (parts.length === 3) {
            let y = parseInt(parts[0], 10);
            let m = parseInt(parts[1], 10);
            let d = parseInt(parts[2], 10);

            if (!isNaN(y) && !isNaN(m) && !isNaN(d)) {
                // Create a base date using UTC to completely ignore local timezone shifts
                const targetReturnDate = new Date(Date.UTC(y, m - 1, d));

                if (durationUnit === 'days') {
                    targetReturnDate.setUTCDate(targetReturnDate.getUTCDate() + durationVal);
                } else if (durationUnit === 'weeks') {
                    targetReturnDate.setUTCDate(targetReturnDate.getUTCDate() + (durationVal * 7));
                } else {
                    targetReturnDate.setUTCMonth(targetReturnDate.getUTCMonth() + durationVal);
                }

                const yyyy = targetReturnDate.getUTCFullYear();
                const mm = String(targetReturnDate.getUTCMonth() + 1).padStart(2, '0');
                const dd = String(targetReturnDate.getUTCDate()).padStart(2, '0');
                const formattedISODate = `${yyyy}-${mm}-${dd}`;

                if (hiddenReturnInput) hiddenReturnInput.value = formattedISODate;

                if (previewReturnText) {
                    const options = { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' };
                    previewReturnText.textContent = targetReturnDate.toLocaleDateString('en-US', options);
                }
            }
        }
    } else {
        if (previewReturnText) previewReturnText.textContent = "--";
        if (hiddenReturnInput) hiddenReturnInput.value = "";
    }

    let totalMonthlyRate = 0;
    let totalItemsCount = 0;

    if (breakdownContainer) breakdownContainer.innerHTML = '';

    productBasket.forEach(item => {
        const itemQty = parseInt(item.quantity) || 1;
        const itemMonthlyPrice = parseFloat(item.rentPrice) || 0;
        
        let rateMultiplier = durationVal;
        if (durationUnit === 'days') {
            rateMultiplier = durationVal / 30.0;
        } else if (durationUnit === 'weeks') {
            rateMultiplier = (durationVal * 7) / 30.0;
        }

        const itemTotalCost = itemMonthlyPrice * itemQty * rateMultiplier;

        totalMonthlyRate += itemMonthlyPrice * itemQty;
        totalItemsCount += itemQty;

        if (breakdownContainer) {
            const breakdownRow = document.createElement('div');
            breakdownRow.style = 'display: flex; justify-content: space-between; font-size: 12px; color: #64748b;';
            breakdownRow.innerHTML = `
              <span>• ${item.name} <small>(${itemQty} × ₱${itemMonthlyPrice.toLocaleString('en-US', {minimumFractionDigits: 2})}/mo)</small></span>
              <span>₱${itemTotalCost.toLocaleString('en-US', {minimumFractionDigits: 2})}</span>
          `;
            breakdownContainer.appendChild(breakdownRow);
        }
    });

    const summaryFillRow = document.getElementById('summary-initial-fill-row');
    const summaryFillVal = document.getElementById('summary-fill-val');
    
    // ALWAYS include fillCost in the calculation if oxygen equipment is present, regardless of checkbox state
    let effectiveFillCost = (fillCost > 0 && productBasket.some(item => isOxygenEquipment(item))) ? fillCost : 0;

    if (effectiveFillCost > 0) {
        if (summaryFillRow) summaryFillRow.style.display = 'flex';
        if (summaryFillVal) summaryFillVal.textContent = `₱${fillCost.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
        
        if (breakdownContainer) {
            const fillRow = document.createElement('div');
            fillRow.style = 'display: flex; justify-content: space-between; font-size: 12px; color: #0284c7; font-weight: 500;';
            fillRow.innerHTML = `
              <span>• Initial Oxygen Tank Content Fill</span>
              <span>₱${fillCost.toLocaleString('en-US', {minimumFractionDigits: 2})}</span>
          `;
            breakdownContainer.appendChild(fillRow);
        }
    } else {
        if (summaryFillRow) summaryFillRow.style.display = 'none';
    }

    if (deliveryFee > 0 && breakdownContainer) {
        const deliveryRow = document.createElement('div');
        deliveryRow.style = 'display: flex; justify-content: space-between; font-size: 12px; color: #0284c7; font-weight: 500;';
        deliveryRow.innerHTML = `
          <span>• Delivery Service Fee</span>
          <span>₱${deliveryFee.toLocaleString('en-US', {minimumFractionDigits: 2})}</span>
        `;
        breakdownContainer.appendChild(deliveryRow);
    }

    let contractMultiplier = durationVal;
    if (durationUnit === 'days') {
        contractMultiplier = durationVal / 30.0;
    } else if (durationUnit === 'weeks') {
        contractMultiplier = (durationVal * 7) / 30.0;
    }

    const itemsSubtotalCost = totalMonthlyRate * contractMultiplier;
    const equipmentBill = itemsSubtotalCost + deliveryFee - voucherAmount;
    
    // Total contract ALWAYS includes effectiveFillCost
    const subtotalContract = equipmentBill + effectiveFillCost;
    const finalVoucher = Math.min(voucherAmount, itemsSubtotalCost + deliveryFee);
    const totalContract = Math.max(subtotalContract, 0);

    // Keep max attribute of amount paid input updated dynamically
    if (amountPaidInput) {
        amountPaidInput.max = totalContract;
    }

    // Sequential Payment Allocation Logic
    let paidTowardFill = 0;
    let paidTowardEquipment = 0;

    if (effectiveFillCost > 0) {
        if (isFillChecked) {
            if (totalAmountPaid >= effectiveFillCost) {
                paidTowardFill = effectiveFillCost;
                let remainder = totalAmountPaid - effectiveFillCost;
                paidTowardEquipment = Math.min(remainder, Math.max(equipmentBill, 0));
            } else {
                paidTowardFill = totalAmountPaid;
                paidTowardEquipment = 0;
            }
        } else {
            paidTowardFill = 0;
            paidTowardEquipment = Math.min(totalAmountPaid, Math.max(equipmentBill, 0));
        }
    } else {
        paidTowardFill = 0;
        paidTowardEquipment = Math.min(totalAmountPaid, Math.max(equipmentBill, 0));
    }

    const balance = totalContract - totalAmountPaid;

    const durationText = document.getElementById('rent-duration-text');
    if (durationText) {
        let unitLabel = durationVal === 1 ? 'Month' : 'Months';
        if (durationUnit === 'days') unitLabel = durationVal === 1 ? 'Day' : 'Days';
        if (durationUnit === 'weeks') unitLabel = durationVal === 1 ? 'Week' : 'Weeks';

        durationText.textContent = `${totalItemsCount} Item${totalItemsCount !== 1 ? 's' : ''} × ${durationVal} ${unitLabel}`;
    }

    const totalBillText = document.getElementById('rent-total-bill');
    if (totalBillText) {
        totalBillText.textContent = `₱${totalContract.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    }

    const voucherRow = document.getElementById('summary-voucher-row');
    const summaryVoucherValText = document.getElementById('summary-voucher-val');
    if (voucherRow && summaryVoucherValText) {
        if (finalVoucher > 0) {
            voucherRow.style.display = 'flex';
            summaryVoucherValText.textContent = `- ₱${finalVoucher.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
        } else {
            voucherRow.style.display = 'none';
        }
    }

    const summaryPaidValText = document.getElementById('summary-paid-val');
    if (summaryPaidValText) {
        summaryPaidValText.textContent = `- ₱${totalAmountPaid.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
        if (effectiveFillCost > 0) {
            summaryPaidValText.title = `Allocated: ₱${paidTowardFill.toFixed(2)} to Fill, ₱${paidTowardEquipment.toFixed(2)} to Equipment`;
        }
    }

    const totalDisplay = document.getElementById('rent-total-display');
    const balanceSubText = document.getElementById('balance-label');

    if (totalDisplay) {
        totalDisplay.textContent = `₱${Math.max(balance, 0).toLocaleString('en-US', {minimumFractionDigits: 2})}`;

        if (balance <= 0 && totalContract > 0) {
            totalDisplay.className = "total-amount-display status-paid";
            if (balanceSubText) {
                balanceSubText.textContent = "Fully Settled";
                balanceSubText.className = "status-paid";
            }
        } else if (totalAmountPaid > 0) {
            totalDisplay.className = "total-amount-display status-pending";
            if (balanceSubText) {
                balanceSubText.textContent = "Partial Balance";
                balanceSubText.className = "status-pending";
          }
        } else {
            totalDisplay.className = "total-amount-display";
            if (balanceSubText) {
                balanceSubText.textContent = durationUnit === 'months' ? "Future monthly dues" : "Due balance";
                balanceSubText.className = "";
          }
        }
    }
}

// INLINE CUSTOMER SEARCH LOGIC & INTERACTION
if (rentCustomerInput && rentCustomerDropdown) {
    rentCustomerInput.addEventListener('focus', () => {
        rentCustomerDropdown.classList.remove('hidden');
    });

    rentCustomerInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        const items = rentCustomerDropdown.querySelectorAll('.customer-option-item');
        let hasMatch = false;

        items.forEach(item => {
            const searchString = item.getAttribute('data-search-string') || '';
            if (searchString.includes(query)) {
                item.style.display = 'flex';
                hasMatch = true;
            } else {
                item.style.display = 'none';
            }
        });

        const noMatch = document.getElementById('no-customer-match');
        if (noMatch) {
            noMatch.style.display = hasMatch || query === '' ? 'none' : 'block';
        }
    });

    rentCustomerDropdown.addEventListener('click', (e) => {
        const item = e.target.closest('.customer-option-item');
        if (!item) return;

        const id = item.getAttribute('data-id');
        const name = item.getAttribute('data-name') || item.querySelector('.cust-name-text')?.innerText.trim() || '';

        if (rentCustomerIdInput) rentCustomerIdInput.value = id;
        if (rentPatientDisplayName) rentPatientDisplayName.innerText = name;
        if (rentCustomerInput) rentCustomerInput.value = name;

        rentCustomerDropdown.classList.add('hidden');
    });
}

if (selectedProductsContainer) {
    selectedProductsContainer.addEventListener('click', (e) => {
        const removeBtn = e.target.closest('.btn-remove-basket-item');
        if (removeBtn) {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();

            const prodId = removeBtn.getAttribute('data-product-id');
            productBasket = productBasket.filter(item => item.id !== prodId);
            renderProductBasket();
        }
    });
}

rentBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        resetRentModal();
        const row = btn.closest('tr');
        if (!row) return;

        const equipmentName = row.cells[1]?.innerText || "Unknown Item";
        const equipmentId = btn.getAttribute('data-product-id') || row.cells[0]?.innerText || "N/A";
        const rentPrice = btn.getAttribute('data-rent-price') || "0.00";
        const stockCount = parseInt(btn.getAttribute('data-stock')) || 1;

        productBasket.push({
            id: equipmentId,
            name: equipmentName,
            rentPrice: rentPrice,
            maxStock: stockCount,
            quantity: 1,
            serials: []
        });

        renderProductBasket();
        rentModal.classList.remove('hidden');
    });
});

document.addEventListener('click', (e) => {
    if (rentCustomerDropdown && !e.target.closest('.customer-search-container')) {
        rentCustomerDropdown.classList.add('hidden');
    }

    if (e.target.classList.contains('close-rent-modal') || e.target.classList.contains('medical-modal-overlay')) {
        if (rentModal && !rentModal.classList.contains('hidden')) {
            rentModal.classList.add('hidden');
            resetRentModal();
        }
    }
});

const rentForm = document.getElementById('rentEntryForm');
if (rentForm) {
    rentForm.addEventListener('submit', (e) => {
        // Ensure serial inputs are fully synced before sending payload
        captureCurrentSerials();

        const totalBillText = document.getElementById('rent-total-bill');
        // Prevent submission if Amount Paid exceeds Total Contract Value
        if (amountPaidInput && totalBillText) {
            const paidVal = parseFloat(amountPaidInput.value) || 0;
            // Parse total contract text value dynamically
            const totalContractVal = parseFloat(totalBillText.textContent.replace('₱', '').replace(/,/g, '')) || 0;

            if (paidVal > totalContractVal) {
                e.preventDefault();
                alert(`Amount paid (₱${paidVal.toFixed(2)}) cannot exceed the total contract bill (₱${totalContractVal.toFixed(2)}).`);
                amountPaidInput.focus();
                return false;
            }
        }
    });

    rentForm.addEventListener('change', (e) => {
        if (e.target.name === 'fulfillment_type') {
            toggleRentDelivery(e.target.value === 'Delivery');
        }
        if (e.target.id === 'rent-payment-method') {
            updateRentRefVisibility();
        }
        if (e.target.id === 'rent-duration-unit') {
            calculateRentalTotals();
        }
    });

    rentForm.addEventListener('input', (e) => {
        if (e.target.id === 'rent-distance-km') {
            updateRentDepositFromDistance();
        }
        calculateRentalTotals();
    });
}

// Clean initialization for dynamic Fill-as-Paid Toggle integration
document.addEventListener("DOMContentLoaded", function () {
    const fillCheckbox = document.getElementById("rent-fill-as-paid-toggle");
    const fillCostField = document.getElementById("rent-fill-cost");
    const amountPaidField = document.getElementById("rent-amount-paid");

    if (fillCheckbox && fillCostField && amountPaidField) {
        fillCheckbox.addEventListener("change", function () {
            const fillCostVal = parseFloat(fillCostField.value) || 0;
            let currentPaidVal = parseFloat(amountPaidField.value) || 0;

            if (fillCheckbox.checked) {
                // Only set it automatically if the field is currently empty or 0
                if (currentPaidVal === 0) {
                    amountPaidField.value = fillCostVal.toFixed(2);
                }
            }
            calculateRentalTotals();
        });
    }
});
/*============= END OF RENTMODAL MULTI-PRODUCT SYSTEM =============*/

/*============= START OF TRANSACTION MODAL CUSTOMER LOGIC =============*/

document.addEventListener('DOMContentLoaded', function() {
    updateRentRefVisibility();

    // Bind explicit change/input change triggers specifically tracking months input modifications
    const durationMonthsInput = document.getElementById('rent-duration-months');
    const rentStartDateInput = document.getElementById('rent-start-date');

    if (durationMonthsInput) {
        durationMonthsInput.addEventListener('input', calculateRentalTotals);
        durationMonthsInput.addEventListener('change', calculateRentalTotals);
    }
    if (rentStartDateInput) {
        rentStartDateInput.addEventListener('change', calculateRentalTotals);
    }

    const txnCustomerSearchInput = document.querySelector('#txnSelectionModal #customer-search-input');
    const txnCustomerDropdownList = document.querySelector('#txnSelectionModal #customer-dropdown-list');
    const txnGlobalCustomerIdInput = document.querySelector('#txnSelectionModal #global-customer-id');

    if (txnCustomerSearchInput && txnCustomerDropdownList) {
        txnCustomerSearchInput.addEventListener('focus', function() {
            txnCustomerDropdownList.classList.remove('hidden');
        });

        txnCustomerSearchInput.addEventListener('input', function(e) {
            const query = e.target.value.toLowerCase().trim();
            const options = txnCustomerDropdownList.querySelectorAll('.customer-option-item');
            let hasMatches = false;

            options.forEach(item => {
                const searchString = item.getAttribute('data-search-string') || '';
                if (searchString.includes(query)) {
                    item.style.display = 'flex';
                    hasMatches = true;
                } else {
                    item.style.display = 'none';
                }
            });

            const noMatchDiv = document.getElementById('no-customer-match');
            if (noMatchDiv) {
                noMatchDiv.style.display = hasMatches || query === '' ? 'none' : 'block';
            }
        });

        txnCustomerDropdownList.addEventListener('click', function(e) {
            const optionItem = e.target.closest('.customer-option-item');
            if (optionItem) {
                const customerId = optionItem.getAttribute('data-id');
                const customerName = optionItem.querySelector('.cust-name-text').textContent.trim();

                if (txnGlobalCustomerIdInput) txnGlobalCustomerIdInput.value = customerId;
                txnCustomerSearchInput.value = customerName;

                txnCustomerDropdownList.classList.add('hidden');
            }
        });

        document.addEventListener('click', function(e) {
            if (!e.target.closest('#txnSelectionModal .customer-search-container')) {
                txnCustomerDropdownList.classList.add('hidden');
            }
        });
    }

    if (typeof productSearchInput !== "undefined" && typeof productDropdownList !== "undefined" && productSearchInput && productDropdownList) {
        productSearchInput.addEventListener('focus', () => productDropdownList.classList.remove('hidden'));

        productSearchInput.addEventListener('input', function(e) {
            const query = e.target.value.toLowerCase().trim();
            const options = productDropdownList.querySelectorAll('.product-option-item');
            let hasMatches = false;

            options.forEach(item => {
                const searchString = item.getAttribute('data-search-string') || '';
                if (searchString.includes(query)) {
                    item.style.display = 'flex';
                    hasMatches = true;
                } else {
                    item.style.display = 'none';
                }
            });

            const noMatchDiv = document.getElementById('no-product-match');
            if (noMatchDiv) {
                noMatchDiv.style.display = hasMatches || query === '' ? 'none' : 'block';
            }
        });

        productDropdownList.addEventListener('click', function(e) {
            const optionItem = e.target.closest('.product-option-item');
            if (optionItem) {
                const id = optionItem.getAttribute('data-id');
                const name = optionItem.getAttribute('data-name');
                const rentPrice = optionItem.getAttribute('data-rent');
                const maxStock = parseInt(optionItem.getAttribute('data-stock')) || 0;

                if (maxStock <= 0) {
                    alert("This medical asset is currently out of stock.");
                    return;
                }

                const existingItem = productBasket.find(item => item.id === id);
                if (existingItem) {
                    if (existingItem.quantity < maxStock) {
                        existingItem.quantity += 1;
                    } else {
                        alert(`Cannot add more. Only ${maxStock} unit(s) available in current inventory.`);
                    }
                } else {
                    productBasket.push({ id, name, rentPrice, maxStock, quantity: 1 });
                }

                productSearchInput.value = '';
                productDropdownList.classList.add('hidden');
                renderProductBasket();
            }
        });

        document.addEventListener('click', function(e) {
            if (!e.target.closest('.product-search-container')) {
                productDropdownList.classList.add('hidden');
            }
        });
    }

    if (typeof selectedProductsContainer !== "undefined" && selectedProductsContainer) {
        selectedProductsContainer.addEventListener('click', function(e) {
            const removeBtn = e.target.closest('.btn-remove-basket-item');
            if (removeBtn) {
                const index = removeBtn.getAttribute('data-index');
                productBasket.splice(index, 1);
                renderProductBasket();
            }
        });
    }

    const purchaseModal = document.getElementById('purchaseAssetModal');
    if (purchaseModal) {
        purchaseModal.addEventListener('click', (e) => {
            if (e.target.classList.contains('close-purchase-modal') || 
                e.target.classList.contains('medical-modal-overlay')) {
                purchaseModal.classList.add('hidden');
                
                const purchaseForm = document.getElementById('purchaseEntryForm');
                if (purchaseForm) purchaseForm.reset();
                
                const purchasePatientDisplayName = document.getElementById('purchase-patient-display-name');
                if (purchasePatientDisplayName) purchasePatientDisplayName.textContent = "No Patient Selected";
                
                resetGlobalCustomerSelection();
            }
        });
    }

    const equipmentSelect = document.getElementById('global-equipment-select');

    document.querySelectorAll('.type-choice-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const flow = this.getAttribute('data-flow');
            

            if (flow === 'Refill') {
                document.getElementById('txnSelectionModal').classList.add('hidden');
                
                const refillModal = document.getElementById('refillAssetModal');
                if (refillModal) {
                    refillModal.classList.remove('hidden');
                }

                return; 
            }

            let productId = "";
            let name = "--";
            let stock = 0;
            let rentPrice = "0.00";
            let salePrice = "0.00";

            if (equipmentSelect) {
                const selectedOption = equipmentSelect.options[equipmentSelect.selectedIndex];
                if (!selectedOption || !selectedOption.value) {
                    alert("Please select equipment first.");
                    return;
                }
                productId = selectedOption.value;
                name = selectedOption.getAttribute('data-name');
                stock = parseInt(selectedOption.getAttribute('data-stock')) || 0;
                rentPrice = selectedOption.getAttribute('data-rent');
                salePrice = selectedOption.getAttribute('data-price');
            } else {
                const fallbackIdInput = document.getElementById('rent-product-id') || document.getElementById('purchase-product-id');
                productId = fallbackIdInput ? fallbackIdInput.value : "";
                name = document.getElementById('rent-equipment-name')?.innerText || "--";
            }

            const activeCustomerId = txnGlobalCustomerIdInput ? txnGlobalCustomerIdInput.value : "";
            const activeCustomerName = txnCustomerSearchInput ? txnCustomerSearchInput.value : "";
            
            // This validation check remains strictly for Rental & Purchase
            if (!activeCustomerId) {
                return;
            }

            document.getElementById('txnSelectionModal').classList.add('hidden');

            if (flow === 'Rental') {
                resetRentModal();
                
                const rentFormGlobalCustomerId = document.querySelector('#rentAssetModal #global-customer-id');
                const rentPatientDisplayName = document.getElementById('rent-patient-display-name');

                if (rentFormGlobalCustomerId) rentFormGlobalCustomerId.value = activeCustomerId;
                if (rentPatientDisplayName) rentPatientDisplayName.textContent = activeCustomerName;

                if (productId) {
                    productBasket.push({
                        id: productId,
                        name: name,
                        rentPrice: rentPrice,
                        maxStock: stock,
                        quantity: 1
                    });
                    renderProductBasket();
                }

                document.getElementById('rentAssetModal').classList.remove('hidden');
                calculateRentalTotals();
            } else {
                // This acts as your fallback choice block for "Sale" / Purchase
                const purchaseFormGlobalCustomerId = document.getElementById('global-purchase-customer-id');
                const purchasePatientDisplayName = document.getElementById('purchase-patient-display-name');

                if (purchaseFormGlobalCustomerId) purchaseFormGlobalCustomerId.value = activeCustomerId;
                if (purchasePatientDisplayName) purchasePatientDisplayName.textContent = activeCustomerName;

                activePurchaseProductId = productId; 

                const purchaseHiddenInput = document.getElementById('purchase-product-id');
                if (purchaseHiddenInput) purchaseHiddenInput.value = productId;

                const qtyInput = document.getElementById('purchase-qty');
                if (qtyInput) {
                    qtyInput.max = stock; 
                    qtyInput.value = stock > 0 ? 1 : 0; 
                }
                
                if (document.getElementById('purchase-equipment-name')) document.getElementById('purchase-equipment-name').innerText = name;
                if (document.getElementById('purchase-stock-display')) document.getElementById('purchase-stock-display').innerText = `${stock} Units Available`;
                if (document.getElementById('purchase-unit-price')) document.getElementById('purchase-unit-price').value = salePrice;
                
                if (typeof updatePurchaseTotal === "function") {
                    updatePurchaseTotal();
                }
                
                document.getElementById('purchaseAssetModal').classList.remove('hidden');
            }
        });
    });
});
/*============= END OF TRANSACTION MODAL CUSTOMER LOGIC =============*/


/*============= START OF REFERENCE NO. LOGIC =============*/

document.addEventListener('DOMContentLoaded', function() {
    const copyButtons = document.querySelectorAll('.btn-copy-hint');

    copyButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const input = this.parentElement.querySelector('.ref-id-input');
            
            if (input) {
                input.select();
                input.setSelectionRange(0, 99999); // Mobile compatibility

                navigator.clipboard.writeText(input.value).then(() => {
                    const icon = this.querySelector('i');
                    const originalIcon = icon ? icon.innerText : 'content_copy';
                    
                    if (icon) icon.innerText = 'check';
                    this.style.color = '#22c55e'; // Success green
                    
                    setTimeout(() => {
                        if (icon) icon.innerText = originalIcon;
                        this.style.color = '';
                    }, 2000);
                }).catch(err => {
                    console.error('Failed to copy text: ', err);
                });
            }
        });
    });
});
/*============= END OF REFERENCE NO. LOGIC =============*/

/*=================================== START OF PRIMEGAS ===================================*/

const primegasModal = document.getElementById('primegasModal');
const productSelect = document.getElementById('primegasProductSelect');
const maxStockSpan = document.getElementById('maxEmptyStock');
const qtyInput = document.getElementById('primegasQty');

// 1. Open Modal & Reset Form
document.querySelector('.type-choice-btn.primegas').addEventListener('click', () => {
    document.getElementById('txnSelectionModal').classList.add('hidden');
    primegasModal.classList.remove('hidden');
    
    // Reset fields on open
    productSelect.value = "";
    maxStockSpan.textContent = "0";
    qtyInput.value = "";
    qtyInput.removeAttribute('max');
});

// 2. Update Max Limit dynamically on change
productSelect.addEventListener('change', function() {
    const selectedOption = this.options[this.selectedIndex];
    const maxStock = parseInt(selectedOption.getAttribute('data-max')) || 0;
    
    // Update display text and input max attribute
    maxStockSpan.textContent = maxStock;
    qtyInput.max = maxStock;
    
    // Reset quantity if it exceeds the new maximum
    if (qtyInput.value && parseInt(qtyInput.value) > maxStock) {
        qtyInput.value = maxStock;
    }
});

// 3. Close Modal
const closePrimegas = () => {
    primegasModal.classList.add('hidden');
};
document.getElementById('close-primegas-modal').addEventListener('click', closePrimegas);
document.getElementById('close-primegas-modal-btn').addEventListener('click', closePrimegas);

/*=================================== END OF PRIMEGAS ===================================*/

/*=================================== START OF ADD PAYMENT MODAL ===================================*/

document.addEventListener('DOMContentLoaded', function() {
    const paymentModal = document.getElementById('addPaymentModal');
    const paymentForm = document.getElementById('payment-form');
    const postBtn = document.getElementById('submit-payment');
    
    // UI Elements inside Modal
    const txnIdInput = document.getElementById('payment-txn-id');
    const summaryRef = document.getElementById('summary-ref');
    const summaryType = document.getElementById('summary-type');
    const summaryBalance = document.getElementById('summary-balance');
    const amountInput = document.getElementById('payment-amount');
    const amountError = document.getElementById('amount-error');
    const rentalQuickPay = document.getElementById('rental-quick-pay');
    const quickPayContainer = document.getElementById('quick-pay-button-container'); // Ensure this ID is in your HTML
    
    // Method/Ref Elements
    const paymentMethodSelect = document.getElementById('payment-method');
    const refGroup = document.getElementById('pm-ref-group');
    const refLabel = document.getElementById('pm-ref-label');
    const refInput = document.getElementById('payment-reference');

    let currentMonthlyRate = 0;
    let currentBalance = 0;
    let currentType = 'Rental';

    // 1. OPEN MODAL & DYNAMICALLY GENERATE BUTTONS
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.btn-add-payment');
        if (!btn) return;

        e.preventDefault();

        // Extract Data
        const txnId = btn.getAttribute('data-txn-id');
        const refNo = btn.getAttribute('data-ref');
        currentType = btn.getAttribute('data-type') || 'Rental';
        currentBalance = parseFloat(btn.getAttribute('data-balance') || 0);
        currentMonthlyRate = parseFloat(btn.getAttribute('data-monthly-rate') || 0);
        const unpaidMonths = parseInt(btn.getAttribute('data-unpaid-count') || 1);

        // Populate Fields
        txnIdInput.value = txnId;
        summaryRef.innerText = refNo || 'N/A';
        summaryType.innerText = currentType;
        summaryBalance.innerText = `₱${currentBalance.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
        amountInput.value = currentBalance.toFixed(2);
        
        amountError.style.display = 'none';

        // 2. DYNAMIC QUICK PAY GENERATION
        if (currentType === 'Rental' && unpaidMonths > 1) {
            rentalQuickPay.style.display = 'block';
            quickPayContainer.innerHTML = ''; // Clear old buttons

            for (let i = 1; i <= unpaidMonths; i++) {
                const pill = document.createElement('button');
                pill.type = 'button';
                pill.className = 'btn-month-pill';
                pill.innerText = `${i}${i === 1 ? 'mo' : 'mos'}`;
                
                pill.onclick = function() {
                    const total = (currentMonthlyRate * i).toFixed(2);
                    amountInput.value = total;
                    
                    // Toggle active class
                    document.querySelectorAll('.btn-month-pill').forEach(b => b.classList.remove('active'));
                    pill.classList.add('active');
                };
                quickPayContainer.appendChild(pill);
            }
            amountInput.placeholder = `Monthly Rate: ₱${currentMonthlyRate.toFixed(2)}`;
        } else {
            rentalQuickPay.style.display = 'none';
        }

        paymentModal.classList.remove('hidden');
    });

    // 3. PAYMENT METHOD LOGIC
    paymentMethodSelect.addEventListener('change', function() {
        const isCash = this.value === 'Cash';
        refGroup.style.display = isCash ? 'none' : 'block';
        refInput.required = !isCash;
        
        if (!isCash) {
            refLabel.innerText = (this.value === 'Check') ? "Check Number" : "Reference Number";
            refInput.placeholder = (this.value === 'Check') ? "Enter check #" : "Enter reference ID";
        }
    });

    // 4. VALIDATION & SUBMIT
    paymentForm.addEventListener('submit', function(e) {
        const amount = parseFloat(amountInput.value);

        if (isNaN(amount) || amount <= 0) {
            e.preventDefault();
            alert("Please enter a valid payment amount.");
            return;
        }

        postBtn.disabled = true;
        postBtn.innerHTML = `<span class="material-symbols-rounded">sync</span> Processing...`;
    });

    // 5. MODAL CLOSE LOGIC
    const closeModal = () => {
        paymentModal.classList.add('hidden');
        paymentForm.reset();
        refGroup.style.display = 'none';
        if(quickPayContainer) quickPayContainer.innerHTML = ''; 
    };

    document.querySelectorAll('#close-payment-modal, #cancel-payment').forEach(el => {
        el.addEventListener('click', closeModal);
    });


});

/*=================================== END OF ADD PAYMENT MODAL ===================================*/

document.addEventListener('DOMContentLoaded', function() {
    // ==========================================
    // 1. TABLE FILTERING & ROUTING CONTROLS
    // ==========================================
    const tableSearch = document.getElementById('table-search');
    const typeFilter = document.getElementById('type-filter');
    const fulfillmentFilter = document.getElementById('fulfillment-filter');
    const statusFilter = document.getElementById('status-filter');
    const rowLimitSelect = document.getElementById('row-limit-select');
    const clearFiltersBtn = document.getElementById('clear-filters-btn');
    const startDateFilter = document.getElementById('start-date-filter');
    const endDateFilter = document.getElementById('end-date-filter');

    // Consolidated filter applier pulling all structural settings parameters together
    function applyFilters() {
        const searchVal = tableSearch ? tableSearch.value.trim() : '';
        const typeVal = typeFilter ? typeFilter.value : '';
        const fulfillmentVal = fulfillmentFilter ? fulfillmentFilter.value : '';
        const statusVal = statusFilter ? statusFilter.value : '';
        const limitVal = rowLimitSelect ? rowLimitSelect.value : '10';
        const startDateVal = startDateFilter ? startDateFilter.value : '';
        const endDateVal = endDateFilter ? endDateFilter.value : '';

        // Construct cleaner search parameters targeting dashboard endpoints
        const urlParams = new URLSearchParams();
        if (searchVal) urlParams.set('q', searchVal);
        if (typeVal) urlParams.set('type', typeVal);
        if (fulfillmentVal) urlParams.set('fulfillment', fulfillmentVal);
        if (statusVal) urlParams.set('status', statusVal);
        if (limitVal !== '10') urlParams.set('limit', limitVal);
        if (startDateVal) urlParams.set('start_date', startDateVal);
        if (endDateVal) urlParams.set('end_date', endDateVal);

        window.location.href = window.location.pathname + '?' + urlParams.toString();
    }

    // Trigger state configurations on active select transitions (instant reload for dropdowns)
    if (typeFilter) typeFilter.addEventListener('change', applyFilters);
    if (fulfillmentFilter) fulfillmentFilter.addEventListener('change', applyFilters);
    if (statusFilter) statusFilter.addEventListener('change', applyFilters);
    if (rowLimitSelect) rowLimitSelect.addEventListener('change', applyFilters);

    // Automatically trigger filtering when dates are picked
    function handleDateChange() {
        const startDateVal = startDateFilter ? startDateFilter.value : '';
        const endDateVal = endDateFilter ? endDateFilter.value : '';

        // Case 1: Both dates are selected -> apply immediately
        if (startDateVal && endDateVal) {
            // Optional Safety: Automatically swap dates if end date is earlier than start date
            if (new Date(startDateVal) > new Date(endDateVal)) {
                startDateFilter.value = endDateVal;
                endDateFilter.value = startDateVal;
            }
            applyFilters();
        } 
        // Case 2: User cleared both dates -> refresh to clear the filter
        else if (!startDateVal && !endDateVal) {
            applyFilters();
        }
    }

    if (startDateFilter) startDateFilter.addEventListener('change', handleDateChange);
    if (endDateFilter) endDateFilter.addEventListener('change', handleDateChange);

    // Search query input box listeners with key down debounce triggers
    if (tableSearch) {
        tableSearch.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                applyFilters();
            }
        });
    }

    // Clear and Reset all filters back to defaults
    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', function() {
            window.location.href = window.location.pathname;
        });
    }

    // Safe Global Pagination Jumper
    window.jumpToPage = function() {
        const jumpInput = document.getElementById('jump-page-input');
        if (!jumpInput) return;

        const targetPage = parseInt(jumpInput.value, 10);
        const maxPage = parseInt(jumpInput.getAttribute('max'), 10);

        if (targetPage >= 1 && targetPage <= maxPage) {
            const urlParams = new URLSearchParams(window.location.search);
            urlParams.set('page', targetPage);
            window.location.href = window.location.pathname + '?' + urlParams.toString();
        } else {
            alert(`Please enter a valid page number between 1 and ${maxPage}.`);
        }
    };


    // ==========================================
    // 2. MODAL CLIENT / PATIENT LOOKUP CONTROLS
    // ==========================================
    const searchInput = document.getElementById('customer-search-input');
    const dropdownList = document.getElementById('customer-dropdown-list');
    const hiddenInput = document.getElementById('global-customer-id');
    const optionItems = document.querySelectorAll('.customer-option-item');
    const noMatchItem = document.getElementById('no-customer-match');

    if (searchInput && dropdownList) {
        searchInput.addEventListener('focus', () => {
            dropdownList.classList.remove('hidden');
        });

        document.addEventListener('click', function(e) {
            if (!e.target.closest('.customer-search-container')) {
                dropdownList.classList.add('hidden');
            }
        });

        searchInput.addEventListener('input', function() {
            const value = this.value.toLowerCase().trim();
            let visibleCount = 0;

            optionItems.forEach(item => {
                const matchString = item.getAttribute('data-search-string') || '';
                if (matchString.includes(value)) {
                    item.style.display = 'flex';
                    visibleCount++;
                } else {
                    item.style.display = 'none';
                }
            });

            if (noMatchItem) {
                if (visibleCount === 0) {
                    noMatchItem.style.display = 'block';
                } else {
                    noMatchItem.style.display = 'none';
                }
            }
        });

        optionItems.forEach(item => {
            item.addEventListener('click', function() {
                const selectedId = this.getAttribute('data-id');
                const nameEl = this.querySelector('.cust-name-text');
                const selectedName = nameEl ? nameEl.textContent.trim() : '';

                if (hiddenInput) hiddenInput.value = selectedId;
                searchInput.value = selectedName;
                
                dropdownList.classList.add('hidden');
                
                optionItems.forEach(el => el.style.backgroundColor = 'transparent');
                this.style.backgroundColor = '#f0fdf4';
            });
        });
    }


    // ==========================================
    // 3. CUSTOM DROPDOWN TOGGLE CONTROLS
    // ==========================================
    const dropdownBtn = document.getElementById("customDropdownBtn");
    const dropdownMenu = document.getElementById("customDropdownMenu");

    if (dropdownBtn && dropdownMenu) {
        dropdownBtn.addEventListener("click", function(event) {
            event.stopPropagation();
            dropdownMenu.classList.toggle("show");
        });

        document.addEventListener("click", function(event) {
            const container = document.getElementById("customActionDropdown");
            if (container && !container.contains(event.target)) {
                dropdownMenu.classList.remove("show");
            }
        });
    }
});
/*============= AUTO-OPEN MODAL FROM URL PARAM =============*/
document.addEventListener('DOMContentLoaded', function() {
    const urlParams = new URLSearchParams(window.location.search);
    const openParam = urlParams.get('open');

    if (openParam === 'sale') {
        const purchaseModal = document.getElementById('purchaseAssetModal');
        if (purchaseModal) {
            purchaseModal.classList.remove('hidden');
        }
    } else if (openParam === 'rental') {
        const rentModal = document.getElementById('rentAssetModal');
        if (rentModal) {
            resetRentModal();
            rentModal.classList.remove('hidden');
        }
    }

    // Clean the URL so refreshing doesn't re-open the modal
    if (openParam) {
        const cleanUrl = window.location.pathname + 
            (window.location.search.replace(/[?&]open=[^&]*/g, '').replace(/^&/, '?') || '');
        window.history.replaceState({}, '', cleanUrl);
    }
});
/*============= END OF AUTO-OPEN MODAL FROM URL PARAM =============*/

/*============= START OF THREE DOTS ACTION =============*/
document.addEventListener('DOMContentLoaded', function() {
    // Inject cancellation modal HTML dynamically if it doesn't already exist
    if (!document.getElementById('cancelTxnModal')) {
        const modalHtml = `
            <div id="cancelTxnModal" style="display: none; position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); z-index: 1050; align-items: center; justify-content: center; font-family: inherit;">
                <div style="background: #ffffff; width: 100%; max-width: 420px; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); overflow: hidden; animation: fadeInModal 0.2s ease-out;">
                    <div style="padding: 18px 20px; border-bottom: 1px solid #e5e7eb; display: flex; align-items: center; justify-content: space-between;">
                        <h3 style="margin: 0; font-size: 16px; font-weight: 600; color: #111827; display: flex; align-items: center; gap: 8px;">
                            <span class="material-symbols-rounded" style="color: #ef4444; font-size: 20px;">cancel</span> Cancel Transaction
                        </h3>
                        <button type="button" id="closeCancelModalX" style="background: none; border: none; cursor: pointer; color: #6b7280; font-size: 20px; padding: 0; display: flex; align-items: center;">&times;</button>
                    </div>
                    <div style="padding: 20px;">
                        <p id="cancelModalDesc" style="margin: 0 0 12px 0; font-size: 13.5px; color: #4b5563; line-height: 1.5;"></p>
                        <div style="margin-bottom: 4px;">
                            <label for="cancelReasonInput" style="display: block; font-size: 12.5px; font-weight: 600; color: #374151; margin-bottom: 6px;">Reason for Cancellation <span style="color: #ef4444;">*</span></label>
                            <textarea id="cancelReasonInput" rows="3" placeholder="Please specify why this transaction is being cancelled..." style="width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13.5px; font-family: inherit; resize: vertical; outline: none; transition: border-color 0.15s;"></textarea>
                            <span id="cancelReasonError" style="display: none; color: #ef4444; font-size: 12px; margin-top: 4px;">A cancellation reason is required.</span>
                        </div>
                    </div>
                    <div style="padding: 12px 20px; background: #f9fafb; border-top: 1px solid #e5e7eb; display: flex; justify-content: flex-end; gap: 8px;">
                        <button type="button" id="cancelModalBtnNo" style="background: #ffffff; color: #374151; border: 1px solid #d1d5db; padding: 8px 14px; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer;">Close</button>
                        <button type="button" id="cancelModalBtnYes" style="background: #ef4444; color: #ffffff; border: none; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">Confirm Cancellation</button>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    }

    const cancelModal = document.getElementById('cancelTxnModal');
    const cancelModalDesc = document.getElementById('cancelModalDesc');
    const cancelReasonInput = document.getElementById('cancelReasonInput');
    const cancelReasonError = document.getElementById('cancelReasonError');
    const cancelModalBtnYes = document.getElementById('cancelModalBtnYes');
    const cancelModalBtnNo = document.getElementById('cancelModalBtnNo');
    const closeCancelModalX = document.getElementById('closeCancelModalX');

    let activeCancelTxnId = null;

    function openCancelModal(txnId, txnType) {
        activeCancelTxnId = txnId;
        cancelReasonInput.value = '';
        cancelReasonError.style.display = 'none';
        cancelReasonInput.style.borderColor = '#d1d5db';
        cancelModalDesc.textContent = `Are you sure you want to cancel this ${txnType.toLowerCase()}? This action cannot be undone and will restore inventory levels.`;
        cancelModal.style.display = 'flex';
        cancelReasonInput.focus();
    }

    function closeCancelModal() {
        cancelModal.style.display = 'none';
        activeCancelTxnId = null;
    }

    cancelModalBtnNo.addEventListener('click', closeCancelModal);
    closeCancelModalX.addEventListener('click', closeCancelModal);
    cancelModal.addEventListener('click', function(e) {
        if (e.target === cancelModal) closeCancelModal();
    });

    cancelReasonInput.addEventListener('input', function() {
        if (cancelReasonInput.value.trim()) {
            cancelReasonError.style.display = 'none';
            cancelReasonInput.style.borderColor = '#d1d5db';
        }
    });

    cancelModalBtnYes.addEventListener('click', function() {
        const reason = cancelReasonInput.value.trim();
        if (!reason) {
            cancelReasonError.style.display = 'block';
            cancelReasonInput.style.borderColor = '#ef4444';
            cancelReasonInput.focus();
            return;
        }

        if (!activeCancelTxnId) return;

        cancelModalBtnYes.disabled = true;
        cancelModalBtnYes.textContent = 'Cancelling...';

        fetch(`/admin/transactions/cancel/${activeCancelTxnId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': window.csrf_token || document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
            },
            body: JSON.stringify({ reason: reason })
        })
        .then(async response => {
            const text = await response.text();
            let data;
            try {
                data = JSON.parse(text);
            } catch (err) {
                // If it's not valid JSON, expose the raw response text for debugging
                throw new Error(`Server error (${response.status}): ${text.substring(0, 100)}`);
            }
            
            if (!response.ok) {
                throw new Error(data.message || `Server returned status ${response.status}`);
            }
            return data;
        })
        .then(data => {
            if (data.success) {
                if (data.pending) {
                    alert(data.message || 'Void request submitted for Administrator approval.');
                }
                window.location.reload();
            } else {
                alert(data.message || 'Failed to cancel the transaction.');
                cancelModalBtnYes.disabled = false;
                cancelModalBtnYes.textContent = 'Confirm Cancellation';
            }
        })
        .catch(error => {
            console.error('Error cancelling transaction:', error);
            alert(error.message || 'A network error occurred. Please try again.');
            cancelModalBtnYes.disabled = false;
            cancelModalBtnYes.textContent = 'Confirm Cancellation';
        });
    });

    // 1. Global click handler para sa dropdown toggling kag auto-close sa gawas
    document.addEventListener('click', function(e) {
        const trigger = e.target.closest('.more-trigger');
        const dropdownMenu = e.target.closest('.dropdown-menu');

        if (trigger) {
            e.stopPropagation();
            const currentDropdown = trigger.nextElementSibling;
            
            // Isara ang iban nga open menus
            document.querySelectorAll('.action-dropdown .dropdown-menu').forEach(menu => {
                if (menu !== currentDropdown) {
                    menu.classList.remove('show');
                }
            });

            // Toggle ang gin-click
            if (currentDropdown) {
                currentDropdown.classList.toggle('show');
            }
            return;
        }

        if (dropdownMenu) {
            return; // Dili pag-isara kung nag-click sa sulod sang menu
        }

        // Isara tanan kung nag-click sa gawas
        document.querySelectorAll('.action-dropdown .dropdown-menu').forEach(menu => {
            menu.classList.remove('show');
        });
    });

    // 2. CSP-Safe Event Listener para sa Cancel Transaction Buttons
    document.addEventListener('click', function(e) {
        const cancelBtn = e.target.closest('.cancel-txn-btn');
        if (!cancelBtn) return;

        const txnId = cancelBtn.getAttribute('data-id');
        const txnType = cancelBtn.getAttribute('data-type') || 'transaction';
        
        // Open modern modal instead of standard prompt/confirm alert
        openCancelModal(txnId, txnType);
    });
});